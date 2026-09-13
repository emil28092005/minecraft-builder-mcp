package io.github.minecraftbuilder.paper;

import com.google.gson.*;
import io.github.minecraftbuilder.core.*;
import org.bukkit.*;
import org.bukkit.command.*;
import org.bukkit.entity.Player;
import org.bukkit.event.*;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.plugin.java.JavaPlugin;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Supplier;

import static io.github.minecraftbuilder.paper.RpcServer.Fault;

public final class BuilderPlugin extends JavaPlugin {
    private final Gson json = new Gson();
    private RpcServer http;
    private ExecutorService disk;
    private EditEngine engine;
    private World world;
    private BuildingWorld access;
    private MaterialCatalog materials;
    private SchematicAssets assets;
    private Region region;
    private String projectId, epoch, owner, adminToken, agentToken;
    private volatile boolean ioBusy, halted;
    private boolean writesPaused;
    private int maxBlocks;
    private final Map<String,TerrainRecipe> terrains = Collections.synchronizedMap(new LinkedHashMap<>());
    private final Map<String,JsonObject> messages = new LinkedHashMap<>();
    private final Map<String,Part> parts = new LinkedHashMap<>();
    private final Map<String,JsonObject> cameras = new LinkedHashMap<>();
    private final Set<String> captureIds = new HashSet<>();
    private final Map<String,Long> leased = new HashMap<>();
    private long lastPoll;
    private String chatClientId;
    private long cameraBusyUntil;
    private String activeCaptureId;
    private final HttpClient cameraHttp = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
    record Part(String id,String name,String operationId,Set<BlockPos> positions,boolean locked) {}

    @Override public void onEnable() {
        try {
            saveDefaultConfig();
            for (String key : List.of("admin-token","agent-token","camera-token"))
                if (getConfig().getString(key,"").isBlank()) getConfig().set(key, randomToken());
            ComponentTokens.validate(getConfig().getString("admin-token"), getConfig().getString("agent-token"), getConfig().getString("camera-token"));
            if (getConfig().getString("world-epoch","").isBlank()) getConfig().set("world-epoch", UUID.randomUUID().toString());
            saveConfig();
            try { Files.setPosixFilePermissions(getDataFolder().toPath().resolve("config.yml"), java.nio.file.attribute.PosixFilePermissions.fromString("rw-------")); }
            catch (UnsupportedOperationException ignored) { }
            projectId=getConfig().getString("project-id","default"); epoch=getConfig().getString("world-epoch"); owner=getConfig().getString("owner-uuid","");
            adminToken=getConfig().getString("admin-token"); agentToken=getConfig().getString("agent-token");
            world=Bukkit.getWorld(getConfig().getString("world","world"));
            if (world==null) throw new IllegalStateException("Configured world is not loaded");
            region=new Region(world.getUID().toString(), configPos("region.min"), configPos("region.max"));
            maxBlocks=Math.min(4096,Math.max(1,getConfig().getInt("max-plan-blocks",4096)));
            access=new BuildingWorld(world);
            materials=new MaterialCatalog();
            assets=new SchematicAssets(getDataFolder().toPath().resolve("schematics"),BuilderPlugin::rotateSchematicState);
            loadMetadata();
            disk=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"mcb-journal");t.setDaemon(true);return t;});
            Limits limits=new Limits(maxBlocks,4096,Math.min(128,Math.max(1,getConfig().getInt("slice-blocks",128))),
                Math.min(5,Math.max(1,getConfig().getInt("slice-millis",5)))*1_000_000L,600_000,32);
            engine=new EditEngine(access,access,new ContextGuard(){
                public void check(Plan plan){guard(plan);}
                public void checkRecovery(Plan plan){guardContext(plan);}
            },new JsonJournal(getDataFolder().toPath().resolve("journal")),limits);
            Bukkit.getPluginManager().registerEvents(new Listener(){
                @EventHandler(priority=EventPriority.MONITOR,ignoreCancelled=true)
                public void placed(BlockPlaceEvent event){if(event.getBlock().getWorld().equals(world))engine.recordExternal(new BlockPos(event.getBlock().getX(),event.getBlock().getY(),event.getBlock().getZ()));}
                @EventHandler(priority=EventPriority.MONITOR,ignoreCancelled=true)
                public void broken(BlockBreakEvent event){if(event.getBlock().getWorld().equals(world))engine.recordExternal(new BlockPos(event.getBlock().getX(),event.getBlock().getY(),event.getBlock().getZ()));}
            },this);
            http=new RpcServer(getConfig().getInt("http-port",8765),adminToken,agentToken,this::rpc);
            Objects.requireNonNull(getCommand("ai")).setExecutor(this::command);
            Bukkit.getScheduler().runTaskTimer(this,this::tick,1,1);
            getLogger().info("Builder ready on loopback port "+http.port()+". Run /ai setup as the project owner.");
        } catch (Exception e) {
            getLogger().severe("Builder disabled: "+e.getMessage());
            getServer().getPluginManager().disablePlugin(this);
        }
    }
    @Override public void onDisable() {
        if(http!=null) http.close();
        if(disk!=null) { disk.shutdown(); try { if(!disk.awaitTermination(3,TimeUnit.SECONDS)) disk.shutdownNow(); } catch(InterruptedException e){Thread.currentThread().interrupt();} }
    }
    private BlockPos configPos(String key) { return new BlockPos(getConfig().getInt(key+".x"),getConfig().getInt(key+".y"),getConfig().getInt(key+".z")); }
    private static String randomToken() { byte[] bytes=new byte[32];new SecureRandom().nextBytes(bytes);return HexFormat.of().formatHex(bytes); }
    private <T>T main(Callable<T> work) throws Exception {
        if(Bukkit.isPrimaryThread()) return work.call();
        Future<T> task=Bukkit.getScheduler().callSyncMethod(this,work);
        try { return task.get(20,TimeUnit.SECONDS); }
        catch(TimeoutException e){task.cancel(false);throw e;}
    }
    private void guard(Plan p) {
        guardContext(p);
        if(halted) throw new Fault("recovery_required","Journal IO failed; restart and inspect recovery");
        if(writesPaused) throw new Fault("cancelled","Writing paused by the owner; send a new request or /ai resume");
        for(Change c:p.changes())if(!c.expected().equals(c.desired()))
            for(Part part:parts.values())if(part.locked()&&part.positions().contains(c.pos()))
                throw new Fault("permission_denied","Part is protected: "+part.name());
    }
    // Recovery inspection/abandonment never writes blocks. Retain its context
    // authorization without applying the pause or protected-part write veto.
    private void guardContext(Plan p) {
        if(!p.projectId().equals(projectId)||!p.worldEpoch().equals(epoch)||!p.region().worldId().equals(world.getUID().toString()))
            throw new Fault("version_mismatch","Project or world changed");
        if(!getConfig().getBoolean("allow-local-automation",false)) {
            Player player=owner.isBlank()?null:Bukkit.getPlayer(UUID.fromString(owner));
            if(player==null||!player.hasPermission("minecraftbuilder.use")) throw new Fault("permission_denied","Project owner must be online and authorised");
        }
        for(Change c:p.changes()) {
            if(!region.contains(c.pos()))throw new Fault("out_of_bounds","Plan exceeds current project area");
        }
        for(Plan.Dependency dependency:p.dependencies())if(!region.contains(dependency.pos()))throw new Fault("out_of_bounds","Dependency exceeds current project area");
    }
    private void scoped(JsonObject p,boolean admin) {
        if(!str(p,"project_id",projectId).equals(projectId))throw new Fault("permission_denied","Unknown project scope");
        String player=str(p,"player_id","");
        if(getConfig().getBoolean("allow-local-automation",false)&&player.equals("console"))return;
        if(owner.isBlank()||!player.equals(owner))throw new Fault("permission_denied","Only the bound project owner can use this capability; run /ai setup");
        Player online=Bukkit.getPlayer(UUID.fromString(owner));
        if(online==null||!online.hasPermission("minecraftbuilder.use"))throw new Fault("permission_denied","Owner is offline or permission was revoked");
    }
    private void available() { if(halted)throw new Fault("recovery_required","Journal unavailable");if(ioBusy)throw new Fault("busy","A journal step is in progress; retry"); }

    private Object rpc(String method,JsonObject p,boolean admin)throws Exception {
        if(method.equals("chat_poll"))return main(()->pollChat(p));
        if(method.equals("chat_reply"))return main(()->reply(p));
        main(()->{scoped(p,admin);return null;});
        switch(method) {
            case "recovery_review":{
                if(!admin)throw new Fault("permission_denied","Recovery requires explicit administrator capability");
                return main(()->engine.reviewRecovery(required(p,"operation_id")));
            }
            case "recovery_abandon":{
                if(!admin)throw new Fault("permission_denied","Recovery requires explicit administrator capability");
                OperationView view=main(()->{available();OperationView v=engine.abandonRecovery(required(p,"operation_id"),required(p,"expected_digest"));ioBusy=true;return v;});
                try{engine.flushOperation(view.id());return status(engine.status(view.id()));}catch(Exception e){halted=true;throw e;}finally{main(()->{ioBusy=false;return null;});}
            }
            case "asset_list":return Map.of("assets",assets.list().stream().filter(a->a.name().toLowerCase(Locale.ROOT).contains(str(p,"query","").toLowerCase(Locale.ROOT))).toList());
            case "schematic_export":{
                Map<BlockPos,String> snapshot=main(()->{
                    Region area=new Region(world.getUID().toString(),pos(p.getAsJsonObject("min")),pos(p.getAsJsonObject("max")));
                    if(!region.contains(area.min())||!region.contains(area.max()))throw new Fault("out_of_bounds","Export exceeds project region");
                    if(area.volume()>maxBlocks)throw new Fault("budget_exceeded","Export at most "+maxBlocks+" blocks");
                    org.bukkit.util.BoundingBox box=new org.bukkit.util.BoundingBox(area.min().x(),area.min().y(),area.min().z(),area.max().x()+1.0,area.max().y()+1.0,area.max().z()+1.0);
                    if(world.getNearbyEntities(box).stream().anyMatch(e->!(e instanceof Player)))throw new Fault("unsupported_entity","Export region contains entities; this prototype exports blocks only");
                    Map<BlockPos,String> data=new LinkedHashMap<>();
                    for(int y=area.min().y();y<=area.max().y();y++)for(int z=area.min().z();z<=area.max().z();z++)for(int x=area.min().x();x<=area.max().x();x++){
                        BlockPos at=new BlockPos(x,y,z);String state=access.getBlock(at);
                        if(world.getBlockAt(x,y,z).getState() instanceof org.bukkit.block.TileState)
                            throw new Fault("unsupported_block_entity","Schematic export cannot retain block-entity data at "+at+"; no asset was written");
                        if(!access.supports(state))throw new Fault("unsupported_block","Export contains unsupported block "+state);data.put(at,state);
                    }return data;
                });
                return assets.exportSnapshot(required(p,"name"),snapshot,p.has("origin")?pos(p.getAsJsonObject("origin")):pos(p.getAsJsonObject("min")),main(()->Bukkit.getUnsafe().getDataVersion()));
            }
            case "schematic_import_prepare":{
                Map<BlockPos,String> data=new LinkedHashMap<>(assets.read(required(p,"asset_id"),pos(p.getAsJsonObject("target")),p.has("rotation")?integer(p,"rotation"):0,main(()->Bukkit.getUnsafe().getDataVersion())));
                Plan plan=main(()->{available();data.replaceAll((at,state)->access.canonical(state));for(BlockPos at:data.keySet())checkSurroundings(at,data);Plan v=engine.prepare(projectId,epoch,region,data,Set.of());ioBusy=true;return v;});
                try{engine.persistPlan(plan.id());return planSummary(plan);}finally{main(()->{ioBusy=false;return null;});}
            }
            case "project_context": return main(this::context);
            case "material_search": return main(()->materials.search(str(p,"query",""),str(p,"kind","block"),p.has("limit")?integer(p,"limit"):null,p.has("cursor")?str(p,"cursor",""):null));
            case "material_describe": return main(()->materials.describe(required(p,"id")));
            case "region_inspect": return main(()->inspect(p));
            case "region_changes": return Map.of("status","resync_required","reason","Prototype uses fresh bounded reads; complete event delta journal is not implemented");
            case "terrain_brush_prepare": {
                TerrainBrush.Spec brush=TerrainBrush.parse(p.getAsJsonObject("brush"));
                record PreparedBrush(TerrainBrush.Result result,Plan plan) {}
                PreparedBrush prepared=main(()->{
                    available();Region scan=brush.bounds();
                    if(!region.contains(scan.min())||!region.contains(scan.max()))throw new Fault("out_of_bounds","Brush scan including halo exceeds project area");
                    Map<BlockPos,String> snapshot=new LinkedHashMap<>();
                    for(int y=scan.min().y();y<=scan.max().y();y++)for(int z=scan.min().z();z<=scan.max().z();z++)for(int x=scan.min().x();x<=scan.max().x();x++){
                        BlockPos at=new BlockPos(x,y,z);snapshot.put(at,access.getBlock(at));
                    }
                    TerrainBrush.Result result=TerrainBrush.compile(brush,snapshot,maxBlocks);
                    if(result.desired().isEmpty())return new PreparedBrush(result,null);
                    Map<BlockPos,String> desired=new LinkedHashMap<>(result.desired());desired.replaceAll((at,state)->access.canonical(state));
                    for(BlockPos at:desired.keySet())checkSurroundings(at,desired);
                    Plan plan=engine.prepare(projectId,epoch,region,desired,result.dependencies());ioBusy=true;
                    return new PreparedBrush(result,plan);
                });
                if(prepared.plan()==null){Map<String,Object> preview=new LinkedHashMap<>(BrushPreview.render(prepared.result()));preview.put("plan_state","empty");preview.put("changed_blocks",0);return preview;}
                try{
                    engine.persistPlan(prepared.plan().id());Map<String,Object> preview=new LinkedHashMap<>(BrushPreview.render(prepared.result()));
                    preview.putAll(planSummary(prepared.plan()));preview.put("plan_state","prepared");return preview;
                }finally{main(()->{ioBusy=false;return null;});}
            }
            case "terrain_preview": {
                TerrainRecipe terrain=new TerrainRecipe(p.getAsJsonObject("recipe"));
                Object preview=TerrainPreview.render(terrain,p.has("resolution")?integer(p,"resolution"):128,maxBlocks);
                synchronized(terrains){terrains.put(terrain.id(),terrain);while(terrains.size()>32)terrains.remove(terrains.keySet().iterator().next());}
                return preview;
            }
            case "terrain_prepare": {
                String terrainId=required(p,"terrain_id");TerrainRecipe terrain=terrains.get(terrainId);
                if(terrain==null)throw new Fault("not_found","Terrain recipe expired or server restarted; call terrain_preview again with the saved recipe");
                int tileIndex=integer(p,"tile_index");TerrainRecipe.Tile tile=terrain.tile(tileIndex,maxBlocks);
                Map<BlockPos,String> desired=new LinkedHashMap<>(tile.blocks());
                Plan plan=main(()->{
                    available();
                    if(!region.contains(tile.bounds().min())||!region.contains(tile.bounds().max()))throw new Fault("out_of_bounds","Terrain tile exceeds current project area");
                    desired.replaceAll((at,state)->access.canonical(state));
                    boolean changed=false;
                    for(BlockPos at:desired.keySet()){
                        String before=access.getBlock(at);changed|=!before.equals(desired.get(at));
                        if(!TerrainRecipe.replaceable(before))throw new Fault("protected_terrain","Tile contains a building or non-terrain block at "+at+"; preserve it explicitly or choose another tile");
                        checkSurroundings(at,desired);
                    }
                    if(!changed)return null;
                    Plan value=engine.prepare(projectId,epoch,region,desired,Set.of());ioBusy=true;return value;
                });
                if(plan==null)return Map.of("status","empty","terrain_id",terrainId,"tile_index",tileIndex,"tile_bounds",tile.bounds(),"changed_blocks",0,"reason","No changed target blocks (unchanged or preserved)");
                try{engine.persistPlan(plan.id());Map<String,Object> summary=new LinkedHashMap<>(planSummary(plan));
                    summary.put("terrain_id",terrainId);summary.put("tile_index",tileIndex);summary.put("tile_bounds",tile.bounds());return summary;
                }finally{main(()->{ioBusy=false;return null;});}
            }
            case "build_prepare": {
                JsonObject recipe=p.getAsJsonObject("recipe");
                Map<BlockPos,String> desired=new LinkedHashMap<>(RecipeCompiler.compile(recipe,maxBlocks));
                Set<BlockPos> dependencies=new LinkedHashSet<>();
                if(p.has("dependencies"))for(JsonElement e:p.getAsJsonArray("dependencies"))dependencies.add(pos(e.getAsJsonObject()));
                if(dependencies.size()>512)throw new Fault("budget_exceeded","At most 512 explicit dependencies supported");
                Plan plan=main(()->{
                    available();
                    desired.replaceAll((k,v)->access.canonical(v));
                    if(p.has("part_id")){
                        Part part=parts.get(required(p,"part_id"));if(part==null)throw new Fault("not_found","Part not found");
                        if(!part.positions().containsAll(desired.keySet()))throw new Fault("out_of_bounds","Patch exceeds the exact part mask; create a new part for an extension");
                    }
                    for(BlockPos at:desired.keySet())checkSurroundings(at,desired);
                    if(p.has("expected_blocks"))ExpectedBlocks.check(p.getAsJsonArray("expected_blocks"),desired.keySet(),access::canonical,access::getBlock,at->BuildingWorld.snapshotId(access.captureBlock(at)));
                    Plan value=engine.prepare(projectId,epoch,region,desired,dependencies);ioBusy=true;return value;
                });
                try { engine.persistPlan(plan.id()); return planSummary(plan); }
                finally {main(()->{ioBusy=false;return null;});}
            }
            case "build_apply": {
                OperationView operation=main(()->{
                    available();Plan plan=engine.plan(required(p,"plan_id"));
                    if(!hash(plan).equals(required(p,"plan_hash")))throw new Fault("stale_snapshot","Plan hash does not match");
                    guard(plan);OperationView value=engine.start(plan.id(),required(p,"idempotency_key"));ioBusy=true;return value;
                });
                try{engine.flushOperation(operation.id());return status(engine.status(operation.id()));}
                catch(Exception e){halted=true;throw e;}
                finally{main(()->{ioBusy=false;return null;});}
            }
            case "operation_status":return main(()->status(engine.status(required(p,"operation_id"))));
            case "operation_cancel":return main(()->status(engine.cancel(required(p,"operation_id"))));
            case "operation_undo_prepare":{
                Plan plan=main(()->{available();Plan value=engine.prepareUndo(required(p,"operation_id"));ioBusy=true;return value;});
                try{engine.persistPlan(plan.id());return planSummary(plan);}finally{main(()->{ioBusy=false;return null;});}
            }
            case "part_define":{
                Object result=main(()->definePart(p));saveMetadata();return result;
            }
            case "part_get":return main(()->{
                Part part=parts.get(required(p,"part_id"));if(part==null)throw new Fault("not_found","Part not found");
                return Map.of("part_id",part.id(),"name",part.name(),"block_count",part.positions().size(),"protected",part.locked(),"operation_id",part.operationId(),"bounds",bounds(part.positions()));
            });
            case "camera_list":return main(()->Map.of("cameras",new ArrayList<>(cameras.values()),"configured",!getConfig().getString("camera-player-uuid","").isBlank()));
            case "camera_capture":return capture(p);
            default:throw new Fault("unsupported_method","Method not implemented: "+method);
        }
    }
    private void checkSurroundings(BlockPos at,Map<BlockPos,String> desired) {
        if(!region.contains(at))throw new Fault("out_of_bounds","Recipe exceeds project region");
        for(BlockPos d:List.of(new BlockPos(1,0,0),new BlockPos(-1,0,0),new BlockPos(0,1,0),new BlockPos(0,-1,0),new BlockPos(0,0,1),new BlockPos(0,0,-1))) {
            BlockPos neighbor=at.add(d);
            if(neighbor.y()<world.getMinHeight()||neighbor.y()>=world.getMaxHeight()||desired.containsKey(neighbor))continue;
            String state=access.getBlock(neighbor);
            if(!access.supports(state))throw new Fault("unsupported_block","Unsupported adjacent environment at "+neighbor+"; use a controlled construction area");
        }
    }
    private Object context() {
        return Map.ofEntries(Map.entry("schema_version",1),Map.entry("project_id",projectId),Map.entry("world_id",world.getUID().toString()),Map.entry("world_epoch",epoch),Map.entry("region",region),
            Map.entry("max_plan_blocks",maxBlocks),Map.entry("checked_expected_blocks",true),Map.entry("parts",parts.values().stream().limit(64).map(p->Map.of("part_id",p.id(),"name",p.name(),"protected",p.locked(),"block_count",p.positions().size())).toList()),
            Map.entry("parts_total",parts.size()),Map.entry("operations",engine.recentOperations(20).stream().map(v->Map.of("operation_id",v.id(),"plan_id",v.planId(),"status",v.status().name().toLowerCase(Locale.ROOT),"written",v.written(),"total_changes",v.totalChanges())).toList()),
            Map.entry("operations_total",engine.operationCount()),Map.entry("truncated",parts.size()>64||engine.operationCount()>20),
            Map.entry("terrain",Map.of("version",1,"features",List.of("hill","ridge","plateau","channel","basin","terrace"),"modes",List.of("sculpt","fill","cut"),"max_cached_recipes",32,"fluid_placement",false,"brush_actions",List.of("raise","lower","flatten","smooth"),"brush_max_scan_blocks",4096)),Map.entry("material_catalog",materials.summary()),Map.entry("recipe",Map.of("version",1,"operations",List.of("box","line","cylinder","repeat"))),Map.entry("capabilities",List.of("material_search","material_describe","region_inspect","build_prepare","build_apply","operation_status","operation_cancel","operation_undo_prepare","part_define","part_get","camera_list","camera_capture","asset_list","schematic_export","schematic_import_prepare","terrain_preview","terrain_prepare","terrain_brush_prepare")),
            Map.entry("block_data",Map.of("all_registered_block_states",true,"fluid_placement",true,"block_entity_snapshots",true,"raw_nbt_editing",false,"item_inventory_editing",false)),
            Map.entry("limitations",List.of("One configured owner and project","Loaded chunks only","No automatic recipe merge","Complete delta journal is not implemented","Camera readiness is heuristic","Schematic v2: entity and block-entity payloads rejected","Later world simulation is not a journaled direct edit")));
    }
    private Object inspect(JsonObject p) {
        Region area=new Region(world.getUID().toString(),pos(p.getAsJsonObject("min")),pos(p.getAsJsonObject("max")));
        if(!region.contains(area.min())||!region.contains(area.max()))throw new Fault("out_of_bounds","Read exceeds project area");
        if(area.volume()>4096)throw new Fault("budget_exceeded","Read at most 4096 blocks per request");
        Map<String,Integer> palette=new TreeMap<>();List<Object> blocks=new ArrayList<>();
        boolean exact=str(p,"detail","summary").equals("blocks");
        long snapshotBytes=0;
        for(int y=area.min().y();y<=area.max().y();y++)for(int z=area.min().z();z<=area.max().z();z++)for(int x=area.min().x();x<=area.max().x();x++){
            BlockPos at=new BlockPos(x,y,z);String state=access.getBlock(at);palette.merge(state,1,Integer::sum);
            if(exact){
                String captured=access.captureBlock(at);snapshotBytes+=captured.getBytes(StandardCharsets.UTF_8).length;
                if(snapshotBytes>8_388_608)throw new Fault("budget_exceeded","Block-entity snapshots exceed 8 MiB; inspect a smaller area");
                Map<String,Object> value=new LinkedHashMap<>(BuildingWorld.publicSnapshot(captured));value.put("pos",at);blocks.add(value);
            }
        }
        return Map.of("region",area,"palette",palette,"blocks",blocks,"sampled_at",System.currentTimeMillis(),"world_epoch",epoch,"truncated",false);
    }
    private Map<String,Object> planSummary(Plan plan) {
        return Map.of("plan_id",plan.id(),"plan_hash",hash(plan),"changed_blocks",plan.changes().stream().filter(c->!c.expected().equals(c.desired())).count(),"region",plan.region(),"expires_at",plan.expiresAtMillis());
    }
    private Map<String,Object> status(OperationView v) {
        return Map.ofEntries(Map.entry("operation_id",v.id()),Map.entry("plan_id",v.planId()),Map.entry("status",v.status().name().toLowerCase(Locale.ROOT)),Map.entry("written",v.written()),Map.entry("total_changes",v.totalChanges()),Map.entry("processed",v.processed()),Map.entry("conflicts",v.conflicts().stream().map(BuilderPlugin::publicConflict).toList()),Map.entry("message",Objects.toString(v.message(),"")));
    }
    private static Map<String,Object> publicConflict(Conflict conflict) {
        Map<String,Object> result=new LinkedHashMap<>();result.put("pos",conflict.pos());result.put("reason",conflict.reason());
        for(var entry:Map.of("expected",conflict.expected(),"current",conflict.current(),"desired",conflict.desired()).entrySet()){
            var snapshot=BuildingWorld.publicSnapshot(entry.getValue());result.put(entry.getKey(),snapshot.get("state"));
            if(snapshot.containsKey("snapshot_id"))result.put(entry.getKey()+"_snapshot_id",snapshot.get("snapshot_id"));
        }
        return result;
    }
    private static String rotateSchematicState(String state,int degrees)throws IOException {
        try{
            var data=Bukkit.createBlockData(state);
            data.rotate(switch(degrees){case 0->org.bukkit.block.structure.StructureRotation.NONE;case 90->org.bukkit.block.structure.StructureRotation.CLOCKWISE_90;case 180->org.bukkit.block.structure.StructureRotation.CLOCKWISE_180;case 270->org.bukkit.block.structure.StructureRotation.COUNTERCLOCKWISE_90;default->throw new IllegalArgumentException("Unsupported rotation");});
            return data.getAsString();
        }catch(IllegalArgumentException failure){throw new IOException("Invalid runtime schematic block state",failure);}
    }
    private String hash(Plan p) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.toJson(p).getBytes(StandardCharsets.UTF_8)));}catch(NoSuchAlgorithmException e){throw new AssertionError(e);}
    }
    private void tick() {
        if(ioBusy||halted||engine==null)return;
        for(OperationView view:engine.pendingOperations()) {
            if(!view.status().terminal()&&lastPoll>0&&System.currentTimeMillis()-lastPoll>15_000&&!getConfig().getBoolean("allow-local-automation",false))engine.cancel(view.id());
            if(view.needsFlush()){flushAsync(view.id());return;}
            if(view.status().terminal())continue;
            try {
                Optional<SliceIntent> next=engine.stageSlice(view.id());
                if(next.isEmpty()){if(engine.status(view.id()).needsFlush())flushAsync(view.id());return;}
                ioBusy=true;SliceIntent intent=next.get();
                disk.submit(()->{
                    try {
                        engine.persistIntent(intent);
                        main(()->{engine.commitSlice(intent);return null;});
                        engine.flushOperation(view.id());
                    }catch(Exception e){halted=true;getLogger().severe("Journal/apply stopped: "+e.getClass().getSimpleName()+"; inspect recovery after restart");}
                    finally{ioBusy=false;}
                });return;
            }catch(Exception e){engine.cancel(view.id());getLogger().warning("Operation stopped: "+e.getMessage());return;}
        }
    }
    private void flushAsync(String id) {
        ioBusy=true;disk.submit(()->{try{engine.flushOperation(id);}catch(Exception e){halted=true;getLogger().severe("Journal flush failed; editing halted");}finally{ioBusy=false;}});
    }
    private Object definePart(JsonObject p) {
        available();OperationView v=engine.status(required(p,"operation_id"));
        if(v.status()!=OperationStatus.APPLIED)throw new Fault("busy","Part requires an applied operation");
        Set<BlockPos> positions=new HashSet<>();
        for(Receipt receipt:engine.receipts(v.id()))positions.add(receipt.change().pos());
        if(positions.isEmpty())throw new Fault("invalid_request","Operation has no owned blocks");
        if(parts.size()>=64)throw new Fault("budget_exceeded","Prototype supports 64 named parts per project");
        for(Part existing:parts.values())if(!Collections.disjoint(existing.positions(),positions))throw new Fault("conflict","Part overlaps "+existing.name());
        String name=required(p,"name");if(name.length()>64)throw new Fault("invalid_request","Part name too long");
        Part value=new Part(UUID.randomUUID().toString(),name,v.id(),Set.copyOf(positions),false);parts.put(value.id(),value);
        return Map.of("part_id",value.id(),"name",name,"block_count",positions.size());
    }
    private Object pollChat(JsonObject request) {
        String client=required(request,"client_id");
        if(chatClientId!=null&&!chatClientId.equals(client)&&!leased.isEmpty()) {
            for(String id:List.copyOf(leased.keySet())) {
                JsonObject old=messages.remove(id);
                if(old!=null){Player p=Bukkit.getPlayer(UUID.fromString(old.get("playerId").getAsString()));if(p!=null)p.sendMessage("[Builder] Bridge restarted. Previous request stopped; check the world before resubmitting.");}
            }
            leased.clear();writesPaused=true;
            for(OperationView v:engine.operations())if(!v.status().terminal())engine.cancel(v.id());
        }
        chatClientId=client;lastPoll=System.currentTimeMillis();List<JsonObject> pending=new ArrayList<>();
        for(var item:messages.entrySet())if(!leased.containsKey(item.getKey())){
            leased.put(item.getKey(),lastPoll);pending.add(item.getValue());if(pending.size()==8)break;
        }
        return Map.of("messages",pending);
    }
    private Object reply(JsonObject p) {
        String id=required(p,"id"),player=required(p,"playerId");JsonObject source=messages.get(id);
        if(source==null||!source.get("playerId").getAsString().equals(player))throw new Fault("permission_denied","Unknown or mismatched chat request");
        Player recipient=Bukkit.getPlayer(UUID.fromString(player));String text=str(p,"text","");
        if(recipient!=null&&!text.isBlank())recipient.sendMessage("[Builder] "+text.substring(0,Math.min(1600,text.length())));
        if(p.has("done")&&p.get("done").getAsBoolean()){messages.remove(id);leased.remove(id);}
        return Map.of("delivered",recipient!=null);
    }
    private boolean command(CommandSender sender,Command cmd,String label,String[] args) {
        try {
            if(!(sender instanceof Player player)){sender.sendMessage("Use RPC for local automation, or /ai in game.");return true;}
            if(!player.hasPermission("minecraftbuilder.use"))throw new Fault("permission_denied","Permission required");
            String sub=args.length==0?"status":args[0];
            if(sub.equals("setup")){
                if(!owner.isBlank()&&!owner.equals(player.getUniqueId().toString()))throw new Fault("permission_denied","Project already bound to another owner");
                owner=player.getUniqueId().toString();getConfig().set("owner-uuid",owner);saveConfig();player.sendMessage("[Builder] Project bound. Set area with /ai area minX minY minZ maxX maxY maxZ; configure Bridge using the private plugin config.");return true;
            }
            if(!player.getUniqueId().toString().equals(owner))throw new Fault("permission_denied","Run /ai setup as the project owner first");
            switch(sub){
                case "area" -> {
                    available();
                    if(args.length==2&&args[1].equals("here")){
                        Location l=player.getLocation();args=new String[]{"area",Integer.toString(l.getBlockX()-24),Integer.toString(Math.max(world.getMinHeight(),l.getBlockY()-1)),Integer.toString(l.getBlockZ()-24),Integer.toString(l.getBlockX()+24),Integer.toString(Math.min(world.getMaxHeight()-1,l.getBlockY()+48)),Integer.toString(l.getBlockZ()+24)};
                    }
                    if(args.length!=7)throw new Fault("invalid_request","/ai area here OR /ai area minX minY minZ maxX maxY maxZ");
                    if(engine.operations().stream().anyMatch(v->!v.status().terminal()))throw new Fault("busy","Stop active operations before changing the area");
                    Region next=new Region(world.getUID().toString(),new BlockPos(Integer.parseInt(args[1]),Integer.parseInt(args[2]),Integer.parseInt(args[3])),new BlockPos(Integer.parseInt(args[4]),Integer.parseInt(args[5]),Integer.parseInt(args[6])));
                    if(next.volume()>2_000_000||!player.getWorld().equals(world)||next.min().y()<world.getMinHeight()||next.max().y()>=world.getMaxHeight())throw new Fault("out_of_bounds","Area must be within the configured world and at most 2 million blocks");
                    region=next;for(String side:List.of("min","max")){BlockPos at=side.equals("min")?region.min():region.max();getConfig().set("region."+side+".x",at.x());getConfig().set("region."+side+".y",at.y());getConfig().set("region."+side+".z",at.z());}saveConfig();player.sendMessage("[Builder] Area set.");
                }
                case "status" -> player.sendMessage("[Builder] project="+projectId+"; operations="+engine.operations().size()+"; bridge="+(System.currentTimeMillis()-lastPoll<15_000?"connected":"offline")+"; halted="+halted);
                case "stop" -> {
                    writesPaused=true;for(OperationView v:engine.operations())if(!v.status().terminal())engine.cancel(v.id());
                    messages.entrySet().removeIf(e->!leased.containsKey(e.getKey()));
                    enqueue(player,"","cancel");player.sendMessage("[Builder] Stopping future writes and agent turn. New writes remain paused until your next request.");
                }
                case "resume" -> {writesPaused=false;player.sendMessage("[Builder] New plans enabled; cancelled operations are not replayed.");}
                case "protect" -> {
                    if(args.length!=2)throw new Fault("invalid_request","/ai protect part-id");Part old=parts.get(args[1]);if(old==null)throw new Fault("not_found","Part not found");
                    parts.put(old.id(),new Part(old.id(),old.name(),old.operationId(),old.positions(),true));disk.submit(()->{try{saveMetadata();}catch(IOException e){halted=true;}});player.sendMessage("[Builder] Part protected.");
                }
                case "camera" -> {
                    if(args.length!=3||!args[1].equals("save"))throw new Fault("invalid_request","/ai camera save name");
                    Location l=player.getLocation();if(!player.getWorld().equals(world)||!region.contains(new BlockPos(l.getBlockX(),l.getBlockY(),l.getBlockZ())))throw new Fault("out_of_bounds","Save a camera inside the configured world and project area");
                    if(args[2].length()>64||cameras.size()>=64&&!cameras.containsKey(args[2]))throw new Fault("budget_exceeded","At most 64 cameras with names up to 64 characters");
                    JsonObject pose=new JsonObject();pose.addProperty("camera_id",args[2]);pose.addProperty("x",l.getX());pose.addProperty("y",l.getY());pose.addProperty("z",l.getZ());pose.addProperty("yaw",l.getYaw());pose.addProperty("pitch",l.getPitch());
                    cameras.put(args[2],pose);disk.submit(()->{try{saveMetadata();}catch(IOException e){halted=true;}});player.sendMessage("[Builder] Camera saved.");
                }
                default -> {if(System.currentTimeMillis()-lastPoll>15_000)throw new Fault("bridge_unavailable","Start the Bridge daemon first");enqueue(player,String.join(" ",args),"prompt");writesPaused=false;player.sendMessage("[Builder] Request queued.");}
            }
        }catch(Exception e){sender.sendMessage("[Builder] "+e.getMessage());}return true;
    }
    private void enqueue(Player player,String text,String type) {
        if(messages.size()>=32&&!type.equals("cancel"))throw new Fault("busy","Chat queue is full");
        if(text.length()>4000)throw new Fault("budget_exceeded","Message too long");
        JsonObject value=new JsonObject();String id=UUID.randomUUID().toString();value.addProperty("id",id);value.addProperty("playerId",player.getUniqueId().toString());value.addProperty("projectId",projectId);value.addProperty("text",text);value.addProperty("type",type);
        Location l=player.getLocation();value.add("playerPosition",json.toJsonTree(Map.of("x",l.getBlockX(),"y",l.getBlockY(),"z",l.getBlockZ(),"yaw",l.getYaw(),"pitch",l.getPitch())));value.addProperty("worldId",player.getWorld().getUID().toString());
        org.bukkit.block.Block target=player.getTargetBlockExact(64);
        if(target!=null)value.add("lookTarget",json.toJsonTree(Map.of("x",target.getX(),"y",target.getY(),"z",target.getZ())));
        messages.put(id,value);
    }
    private Object capture(JsonObject p)throws Exception {
        if(p.has("capture_id")){
            String id=required(p,"capture_id");if(!main(()->captureIds.contains(id)))throw new Fault("permission_denied","Unknown capture");
            JsonObject result=cameraRequest("GET","/v1/captures/"+id,null);
            if(!str(result,"status","pending").equals("pending"))main(()->{if(id.equals(activeCaptureId)){cameraBusyUntil=0;activeCaptureId=null;}return null;});
            return result;
        }
        JsonObject pose=main(()->{
            if(p.has("after_operation_id")&&engine.status(required(p,"after_operation_id")).status()!=OperationStatus.APPLIED)throw new Fault("capture_not_ready","Operation not yet applied");
            JsonObject result=p.has("pose")?p.getAsJsonObject("pose").deepCopy():cameras.get(required(p,"camera_id"));
            if(result==null)throw new Fault("not_found","Camera not found");result=result.deepCopy();
            result.remove("camera_id");
            for(String key:result.keySet())if(!Set.of("x","y","z","yaw","pitch","fov","width","height").contains(key))throw new Fault("invalid_request","Unknown camera field: "+key);
            double yaw=number(result,"yaw"),pitch=number(result,"pitch");
            if(yaw < -360 || yaw > 360 || pitch < -90 || pitch > 90)throw new Fault("invalid_request","Camera yaw/pitch out of range");
            if(result.has("fov")&&(integer(result,"fov")<30||integer(result,"fov")>110))throw new Fault("invalid_request","FOV must be an integer 30..110");
            if(result.has("width")&&(integer(result,"width")<320||integer(result,"width")>1920)||result.has("height")&&(integer(result,"height")<180||integer(result,"height")>1080))throw new Fault("invalid_request","Capture dimensions out of range");
            double x=number(result,"x"),y=number(result,"y"),z=number(result,"z");
            if(!region.contains(new BlockPos((int)Math.floor(x),(int)Math.floor(y),(int)Math.floor(z))))throw new Fault("out_of_bounds","Camera exceeds project area");
            result.addProperty("dimension",world.getKey().asString());if(p.has("after_operation_id"))result.addProperty("afterOperationId",required(p,"after_operation_id"));return result;
        });
        CompletableFuture<Boolean> teleport=main(()->{
            String uuid=getConfig().getString("camera-player-uuid","");if(uuid.isBlank())throw new Fault("camera_unavailable","Configure a spectator camera account");
            Player camera=Bukkit.getPlayer(UUID.fromString(uuid));if(camera==null||camera.getGameMode()!=GameMode.SPECTATOR)throw new Fault("camera_unavailable","Configured spectator camera must be online");
            if(cameraBusyUntil>System.currentTimeMillis())throw new Fault("busy","A capture is already in progress; poll it before moving the camera");
            cameraBusyUntil=System.currentTimeMillis()+45_000;
            return camera.teleportAsync(new Location(world,number(pose,"x"),number(pose,"y"),number(pose,"z"),(float)number(pose,"yaw"),(float)number(pose,"pitch")));
        });
        try{
            if(!teleport.get(15,TimeUnit.SECONDS))throw new Fault("camera_unavailable","Camera teleport was rejected");
            JsonObject response=cameraRequest("POST","/v1/capture",pose);
            if(response.has("captureId"))main(()->{if(captureIds.size()>256)captureIds.clear();activeCaptureId=response.get("captureId").getAsString();captureIds.add(activeCaptureId);return null;});
            return response;
        }catch(Exception e){main(()->{cameraBusyUntil=0;activeCaptureId=null;return null;});throw e;}
    }
    private JsonObject cameraRequest(String method,String path,JsonObject body)throws Exception {
        HttpRequest.Builder request=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+getConfig().getInt("camera-port",8766)+path)).timeout(Duration.ofSeconds(25)).header("Authorization","Bearer "+getConfig().getString("camera-token")).header("Content-Type","application/json");
        if(method.equals("POST"))request.POST(HttpRequest.BodyPublishers.ofString(json.toJson(body)));else request.GET();
        HttpResponse<InputStream> response=cameraHttp.send(request.build(),HttpResponse.BodyHandlers.ofInputStream());
        try(InputStream in=response.body()){
            byte[] bytes=in.readNBytes(12*1024*1024+1);if(bytes.length>12*1024*1024)throw new Fault("budget_exceeded","Camera response too large");
            if(response.statusCode()>=400)throw new Fault("camera_unavailable","Camera service returned HTTP "+response.statusCode());
            return JsonParser.parseString(new String(bytes,StandardCharsets.UTF_8)).getAsJsonObject();
        }
    }
    private synchronized void saveMetadata()throws IOException {
        JsonObject data;
        try{data=main(()->{JsonObject value=new JsonObject();value.add("parts",json.toJsonTree(parts.values()));value.add("cameras",json.toJsonTree(cameras));return value;});}
        catch(Exception e){throw new IOException("Cannot snapshot metadata",e);}
        Path path=getDataFolder().toPath().resolve("metadata.json"),temp=path.resolveSibling("metadata.tmp");
        Files.writeString(temp,json.toJson(data));Files.move(temp,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
    }
    private void loadMetadata()throws IOException {
        Path path=getDataFolder().toPath().resolve("metadata.json");if(!Files.exists(path))return;
        JsonObject data=JsonParser.parseString(Files.readString(path)).getAsJsonObject();
        for(JsonElement e:data.getAsJsonArray("parts")){Part part=json.fromJson(e,Part.class);parts.put(part.id(),part);}
        for(var e:data.getAsJsonObject("cameras").entrySet())cameras.put(e.getKey(),e.getValue().getAsJsonObject());
    }
    private static String required(JsonObject p,String key){String value=str(p,key,"");if(value.isBlank()||value.length()>256)throw new Fault("invalid_request","Required bounded string: "+key);return value;}
    private static String str(JsonObject p,String key,String fallback){return p.has(key)&&!p.get(key).isJsonNull()?p.get(key).getAsString():fallback;}
    private static BlockPos pos(JsonObject p){return new BlockPos(integer(p,"x"),integer(p,"y"),integer(p,"z"));}
    private Region bounds(Set<BlockPos> positions){
        return new Region(world.getUID().toString(),new BlockPos(positions.stream().mapToInt(BlockPos::x).min().orElseThrow(),positions.stream().mapToInt(BlockPos::y).min().orElseThrow(),positions.stream().mapToInt(BlockPos::z).min().orElseThrow()),new BlockPos(positions.stream().mapToInt(BlockPos::x).max().orElseThrow(),positions.stream().mapToInt(BlockPos::y).max().orElseThrow(),positions.stream().mapToInt(BlockPos::z).max().orElseThrow()));
    }
    private static int integer(JsonObject p,String key){try{return p.get(key).getAsBigDecimal().intValueExact();}catch(Exception e){throw new Fault("invalid_request","Integer coordinate required: "+key);}}
    private static double number(JsonObject p,String key){double v=p.get(key).getAsDouble();if(!Double.isFinite(v))throw new Fault("invalid_request","Finite number required");return v;}
}
