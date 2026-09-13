package probe;
import org.bukkit.*;
import org.bukkit.block.data.BlockData;
import org.bukkit.command.*;
import org.bukkit.plugin.java.JavaPlugin;
import java.lang.reflect.*;
import java.nio.file.*;
import java.time.Instant;
import java.util.*;

/** Test-only, console-only helper; never installed in the user's lobby server. */
public final class MaterialRegistryProbe extends JavaPlugin {
  private final List<Map<String,Object>> failures = new ArrayList<>();
  private int failureCount;
  @Override public void onEnable() { getLogger().info("Use console registryprobe to run the isolated registry test"); }
  @Override public boolean onCommand(CommandSender sender, Command cmd, String label, String[] args) {
    if (sender instanceof ConsoleCommandSender) runProbe(); return true;
  }
  private static Method method(Class<?> c, String name, Class<?>... args) throws Exception {
    Method result=c.getDeclaredMethod(name,args); result.setAccessible(true); return result;
  }
  private static Object call(Method m, Object receiver, Object... args) throws Throwable {
    try { return m.invoke(receiver,args); } catch(InvocationTargetException e) { throw e.getCause(); }
  }
  private static void equal(Object expected,Object actual) { if (!Objects.equals(expected,actual)) throw new AssertionError("snapshot_mismatch"); }
  private void failure(String id,String state,String phase,Throwable error) {
    failureCount++;
    if(failures.size()<128) failures.add(Map.of("block",id,"state",state,"phase",phase,"reason",error.getClass().getSimpleName()));
  }
  private void runProbe() {
    long start=System.nanoTime(); failures.clear(); failureCount=0;
    int total=0,passed=0,entityDefaults=0,catalogDescribed=0,registryCount=0,maxDescriptionBytes=0,maxProperties=0,maxPropertyValues=0;
    int propertyCases=0,propertyPassed=0,freshPassed=0,sameMaterialPassed=0,privateUndoPassed=0;
    World anchorWorld=null; BlockData anchorBefore=null; boolean anchorRestored=false;
    String fatal=null; Map<?,?> catalogSummary=Map.of();
    try {
      var plugin=Bukkit.getPluginManager().getPlugin("MinecraftBuilderMCP"); var loader=plugin.getClass().getClassLoader();
      Class<?> accessClass=Class.forName("io.github.minecraftbuilder.paper.BuildingWorld",true,loader);
      Class<?> catalogClass=Class.forName("io.github.minecraftbuilder.paper.MaterialCatalog",true,loader);
      Constructor<?> catalogConstructor=catalogClass.getDeclaredConstructor(); catalogConstructor.setAccessible(true);
      Object catalog=catalogConstructor.newInstance(); Method describe=method(catalogClass,"describe",String.class);
      catalogSummary=(Map<?,?>)call(method(catalogClass,"summary"),catalog); registryCount=(int)Registry.BLOCK.stream().count();
      Class<?> posClass=Class.forName("io.github.minecraftbuilder.core.BlockPos",true,loader);
      Constructor<?> constructor=accessClass.getDeclaredConstructor(World.class); constructor.setAccessible(true);
      World world=Bukkit.getWorld("world");
      if(world==null||Bukkit.getPort()!=25576) throw new IllegalStateException("IsolatedServerRequired");
      world.loadChunk(0,0); Object pos=posClass.getConstructor(int.class,int.class,int.class).newInstance(4,100,4);
      if(!world.getBlockAt(4,100,4).getType().isAir()||!world.getBlockAt(5,100,4).getType().isAir()) throw new IllegalStateException("AirFixtureRequired");
      anchorWorld=world; anchorBefore=world.getBlockAt(5,100,4).getBlockData();
      world.getBlockAt(5,100,4).setBlockData(Material.STONE.createBlockData(),false);
      Object access=constructor.newInstance(world);
      Method capture=method(accessClass,"captureBlock",posClass),prepare=method(accessClass,"prepareBlock",posClass,String.class,String.class),place=method(accessClass,"setCapturedBlock",posClass,String.class);
      String before=(String)call(capture,access,pos);
      for(Material material:Material.values()) {
        if(material.isLegacy()||!material.isBlock()) continue;
        total++; String id=material.getKey().toString(); Map<?,?> properties=Map.of();
        try {
          Map<?,?> description=(Map<?,?>)call(describe,catalog,id);
          maxDescriptionBytes=Math.max(maxDescriptionBytes,new com.google.gson.Gson().toJson(description).getBytes(java.nio.charset.StandardCharsets.UTF_8).length);
          properties=(Map<?,?>)description.get("properties"); maxProperties=Math.max(maxProperties,properties.size());
          for(Object values:properties.values()) maxPropertyValues=Math.max(maxPropertyValues,((Collection<?>)values).size());
          catalogDescribed++;
        } catch(Throwable e) { failure(id,id,"catalog_description",e); }
        String defaultState=material.createBlockData().getAsString(),phase="prepare_default",base=null;
        try {
          base=(String)call(prepare,access,pos,defaultState,before); if(base.startsWith("\u0000")) entityDefaults++;
          equal(before,call(capture,access,pos));
          phase="place_default"; call(place,access,pos,base);
          phase="verify_default"; equal(base,call(capture,access,pos)); passed++;
        } catch(Throwable e) { failure(id,defaultState,phase,e); }
        finally { call(place,access,pos,before); equal(before,call(capture,access,pos)); }
        if(base==null) continue;
        Set<String> variants=new LinkedHashSet<>();
        for(var property:properties.entrySet()) for(Object value:(Collection<?>)property.getValue())
          variants.add(Bukkit.createBlockData(id+"["+property.getKey()+"="+value+"]").getAsString());
        for(String variant:variants) {
          if(++propertyCases>30_000||System.nanoTime()-start>35_000_000_000L) throw new IllegalStateException("ProbeBudgetExceeded");
          phase="prepare_fresh_property";
          try {
            String desired=(String)call(prepare,access,pos,variant,before); equal(before,call(capture,access,pos));
            phase="place_fresh_property"; call(place,access,pos,desired);
            phase="verify_fresh_property"; equal(desired,call(capture,access,pos)); freshPassed++;
            call(place,access,pos,before); equal(before,call(capture,access,pos));
            phase="place_existing_default"; call(place,access,pos,base); equal(base,call(capture,access,pos));
            phase="prepare_same_material"; String changed=(String)call(prepare,access,pos,variant,base); equal(base,call(capture,access,pos));
            phase="place_same_material"; call(place,access,pos,changed);
            phase="verify_same_material"; equal(changed,call(capture,access,pos)); sameMaterialPassed++;
            phase="private_undo"; call(place,access,pos,base); equal(base,call(capture,access,pos)); privateUndoPassed++; propertyPassed++;
          } catch(Throwable e) { failure(id,variant,phase,e); }
          finally { call(place,access,pos,before); equal(before,call(capture,access,pos)); }
        }
      }
    } catch(Throwable e) { fatal=e.getClass().getSimpleName(); }
    finally {
      if(anchorWorld!=null&&anchorBefore!=null) {
        anchorWorld.getBlockAt(5,100,4).setBlockData(anchorBefore,false);
        anchorRestored=anchorBefore.equals(anchorWorld.getBlockAt(5,100,4).getBlockData());
      }
    }
    double millis=(System.nanoTime()-start)/1_000_000.0;
    Map<String,Object> result=new LinkedHashMap<>();
    result.put("timestamp",Instant.now().toString());result.put("server_version",Bukkit.getVersion());
    result.put("fixture","Air target (4,100,4); temporary stone section anchor (5,100,4)");result.put("anchor_restored",anchorRestored);
    result.put("catalog_summary",catalogSummary);result.put("catalog_described",catalogDescribed);result.put("registry_blocks",registryCount);
    result.put("max_description_bytes",maxDescriptionBytes);result.put("max_properties",maxProperties);result.put("max_property_values",maxPropertyValues);
    result.put("total",total);result.put("passed",passed);result.put("entity_defaults",entityDefaults);
    result.put("property_cases",propertyCases);result.put("property_passed",propertyPassed);result.put("fresh_property_passed",freshPassed);
    result.put("same_material_property_passed",sameMaterialPassed);result.put("private_undo_passed",privateUndoPassed);
    result.put("duration_ms",millis);result.put("fatal",fatal);result.put("failure_count",failureCount);result.put("failures",failures);
    try { getDataFolder().mkdirs(); Files.writeString(getDataFolder().toPath().resolve("report.json"),new com.google.gson.GsonBuilder().serializeNulls().create().toJson(result)); }
    catch(Exception e) { getLogger().severe("Could not save registry probe report"); }
    getLogger().info("Registry probe: "+passed+"/"+total+", property cases "+propertyPassed+"/"+propertyCases+", failures "+failureCount+", fatal "+fatal+", "+Math.round(millis)+" ms");
  }
}
