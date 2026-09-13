package io.github.minecraftbuilder.core;

import com.google.gson.*;
import java.util.*;

/** Relative brush over one bounded immutable snapshot. Does not access or mutate a world. */
public final class TerrainBrush {
    public record Spec(Region bounds, int centerX, int centerZ, int radius, String action,
                       int amount, int targetHeight, double strength, double falloff, int smoothRadius,
                       List<Region> preserve) {
        public Spec {
            Objects.requireNonNull(bounds);preserve=List.copyOf(preserve);
            if(bounds.volume()>4096 || bounds.volume()<1)throw bad("Brush scan window must contain at most 4096 cells");
            if(radius<1||radius>16||smoothRadius<1||smoothRadius>3)throw bad("Radius must be 1..16; smoothing radius 1..3");
            if(!Set.of("raise","lower","flatten","smooth").contains(action))throw bad("Unknown brush action");
            if(amount<1||amount>32||!Double.isFinite(strength)||strength<0||strength>1||!Double.isFinite(falloff)||falloff<0||falloff>1)throw bad("Invalid brush strength, falloff or amount");
            int halo=action.equals("smooth")?smoothRadius:0;
            if((long)centerX-radius-halo<bounds.min().x()||(long)centerX+radius+halo>bounds.max().x()
                ||(long)centerZ-radius-halo<bounds.min().z()||(long)centerZ+radius+halo>bounds.max().z())throw bad("Scan window must include the whole brush and smoothing halo");
            if(preserve.size()>64)throw bad("At most 64 preserve boxes");
            for(Region p:preserve)if(!bounds.contains(p.min())||!bounds.contains(p.max()))throw bad("Preserve box exceeds scan window");
        }
    }
    public record Result(Map<BlockPos,String> desired, Set<BlockPos> dependencies, Region bounds,
                         int[][] before, int[][] after, int changedColumns, int raisedBlocks, int loweredBlocks) { }
    private TerrainBrush() { }
    public static Spec parse(JsonObject j) {
        fields(j,"min","max","center","radius","action","amount","height","strength","falloff","smooth_radius","preserve");
        Region bounds=new Region("brush",pos(obj(j,"min")),pos(obj(j,"max")));
        JsonObject center=obj(j,"center");fields(center,"x","z");String action=text(j,"action");
        if((action.equals("raise")||action.equals("lower"))&&!j.has("amount"))throw bad("raise/lower require amount");
        if(action.equals("flatten")&&!j.has("height"))throw bad("flatten requires height");
        if(j.has("amount")&&!Set.of("raise","lower").contains(action))throw bad("amount is only for raise/lower");
        if(j.has("height")&&!action.equals("flatten"))throw bad("height is only for flatten");
        if(j.has("smooth_radius")&&!action.equals("smooth"))throw bad("smooth_radius is only for smooth");
        List<Region> preserves=new ArrayList<>();
        if(j.has("preserve")){
            if(!j.get("preserve").isJsonArray()||j.getAsJsonArray("preserve").size()>64)throw bad("Invalid preserve boxes");
            for(JsonElement e:j.getAsJsonArray("preserve")){if(!e.isJsonObject())throw bad("Invalid preserve box");JsonObject p=e.getAsJsonObject();fields(p,"min","max");preserves.add(new Region("brush",pos(obj(p,"min")),pos(obj(p,"max"))));}
        }
        return new Spec(bounds,integer(center,"x"),integer(center,"z"),integer(j,"radius"),action,
            j.has("amount")?integer(j,"amount"):1,j.has("height")?integer(j,"height"):0,
            j.has("strength")?number(j,"strength"):1,j.has("falloff")?number(j,"falloff"):0.5,
            j.has("smooth_radius")?integer(j,"smooth_radius"):1,preserves);
    }
    public static Result compile(Spec spec,Map<BlockPos,String> snapshot,int budget) {
        Region b=spec.bounds();if(snapshot.size()!=b.volume())throw bad("Snapshot must cover the entire scan window");
        int width=b.max().x()-b.min().x()+1,length=b.max().z()-b.min().z()+1;
        int[][] before=new int[length][width],after=new int[length][width];
        for(int z=b.min().z();z<=b.max().z();z++)for(int x=b.min().x();x<=b.max().x();x++){
            int top=Integer.MIN_VALUE;
            for(int y=b.max().y();y>=b.min().y();y--){
                String state=snapshot.get(new BlockPos(x,y,z));if(state==null)throw bad("Missing snapshot cell");
                if(!TerrainRecipe.replaceable(state))throw bad("Brush scan contains a non-terrain block at "+new BlockPos(x,y,z));
                if(!air(state)&&top==Integer.MIN_VALUE)top=y;
            }
            if(top==Integer.MIN_VALUE)throw bad("No terrain surface in column "+x+","+z+"; extend scan downward");
            if(top==b.max().y())throw bad("Surface touches scan ceiling at "+x+","+z+"; include air above terrain");
            before[z-b.min().z()][x-b.min().x()]=top;after[z-b.min().z()][x-b.min().x()]=top;
        }
        Map<BlockPos,String> desired=new LinkedHashMap<>();int columns=0,raised=0,lowered=0;
        for(int z=b.min().z();z<=b.max().z();z++)for(int x=b.min().x();x<=b.max().x();x++){
            double distance=Math.hypot((long)x-spec.centerX(),(long)z-spec.centerZ());
            if(distance>spec.radius())continue;
            double weight=weight(distance,spec.radius(),spec.falloff())*spec.strength();
            int old=before[z-b.min().z()][x-b.min().x()];double target;
            switch(spec.action()){
                case "raise" -> target=old+spec.amount();
                case "lower" -> target=old-spec.amount();
                case "flatten" -> target=spec.targetHeight();
                case "smooth" -> {
                    long sum=0;int count=0,r=spec.smoothRadius();
                    for(int dz=-r;dz<=r;dz++)for(int dx=-r;dx<=r;dx++){
                        sum+=before[z+dz-b.min().z()][x+dx-b.min().x()];count++;
                    }
                    target=(double)sum/count;
                }
                default -> throw new AssertionError();
            }
            // Symmetric rounding of displacement: lowering and raising have equal strength.
            double delta=(target-old)*weight;int next=old+(int)(Math.copySign(Math.floor(Math.abs(delta)+0.5),delta));
            if(next==old)continue;
            if(next<b.min().y()||next>=b.max().y())throw bad("Target surface leaves scan window; extend vertical bounds (keep air above)");
            int from=Math.min(old,next),to=Math.max(old,next);
            boolean protectedColumn=false;
            for(int y=from;y<=to;y++){BlockPos at=new BlockPos(x,y,z);if(spec.preserve().stream().anyMatch(p->p.contains(at))){protectedColumn=true;break;}}
            if(protectedColumn)continue; // Preserve the whole edit column instead of tearing a hole in the terrain.
            String top=snapshot.get(new BlockPos(x,old,z));
            if(next>old){
                String under=snapshot.get(new BlockPos(x,old-1,z));
                String fill=under!=null&&!air(under)?under:subsoil(top);
                // Move the top surface up, using existing subsoil rather than burying grass layers.
                for(int y=old;y<next;y++)desired.put(new BlockPos(x,y,z),fill);
                desired.put(new BlockPos(x,next,z),top);raised+=next-old;
            }else{
                // Do not fill a cave when cutting: a new cap must sit on existing solid terrain.
                if(air(snapshot.get(new BlockPos(x,next,z))))throw bad("Cut would expose a void; choose a shallower cut or another area");
                for(int y=next+1;y<=old;y++)desired.put(new BlockPos(x,y,z),"minecraft:air");
                desired.put(new BlockPos(x,next,z),top);lowered+=old-next;
            }
            after[z-b.min().z()][x-b.min().x()]=next;columns++;
        }
        desired.entrySet().removeIf(e->e.getValue().equals(snapshot.get(e.getKey())));
        if(desired.size()>budget)throw bad("Brush exceeds plan budget; use a smaller radius or amount");
        return new Result(Collections.unmodifiableMap(desired),Set.copyOf(snapshot.keySet()),b,before,after,columns,raised,lowered);
    }
    private static boolean air(String s){return s!=null&&Set.of("minecraft:air","minecraft:cave_air","minecraft:void_air").contains(s);}
    private static String subsoil(String top){return top.startsWith("minecraft:grass_block")||top.equals("minecraft:moss_block")?"minecraft:dirt":top;}
    private static double weight(double d,int radius,double falloff){if(falloff==0)return 1;double core=radius*(1-falloff);if(d<=core)return 1;double t=Math.min(1,(d-core)/(radius-core));return 1-t*t*(3-2*t);}
    private static IllegalArgumentException bad(String m){return new IllegalArgumentException(m);}
    private static JsonObject obj(JsonObject j,String k){if(j==null||!j.has(k)||!j.get(k).isJsonObject())throw bad("Expected object: "+k);return j.getAsJsonObject(k);}
    private static String text(JsonObject j,String k){if(!j.has(k)||!j.get(k).isJsonPrimitive()||!j.getAsJsonPrimitive(k).isString())throw bad("Expected text: "+k);return j.get(k).getAsString();}
    private static double number(JsonObject j,String k){if(!j.has(k)||!j.get(k).isJsonPrimitive()||!j.getAsJsonPrimitive(k).isNumber())throw bad("Expected number: "+k);double n=j.get(k).getAsDouble();if(!Double.isFinite(n))throw bad("Nonfinite number");return n;}
    private static int integer(JsonObject j,String k){number(j,k);try{return j.get(k).getAsBigDecimal().intValueExact();}catch(Exception e){throw bad("Expected 32-bit integer: "+k);}}
    private static BlockPos pos(JsonObject j){fields(j,"x","y","z");int x=integer(j,"x"),y=integer(j,"y"),z=integer(j,"z");if(Math.abs((long)x)>30_000_000||Math.abs((long)z)>30_000_000||y< -4096||y>4096)throw bad("Coordinate out of range");return new BlockPos(x,y,z);}
    private static void fields(JsonObject j,String... keys){if(j==null)throw bad("Expected brush object");Set<String> allowed=Set.of(keys);for(String k:j.keySet())if(!allowed.contains(k))throw bad("Unknown brush field: "+k);}
}
