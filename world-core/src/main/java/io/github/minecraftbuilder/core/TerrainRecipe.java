package io.github.minecraftbuilder.core;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/** Pure world-coordinate height field. Tiling never changes noise, features or surface layers. */
public final class TerrainRecipe {
    public static final Set<String> MATERIALS = Set.of("stone", "andesite", "granite", "diorite",
        "deepslate", "cobbled_deepslate", "dirt", "grass_block", "moss_block", "sandstone", "terracotta");
    private final Region bounds;
    private final int base, seed, depth;
    private final double amplitude, scale;
    private final String mode, rock, soil, surface, id;
    private final List<Feature> features;
    private final List<Region> preserves;
    private record Point(double x, double z) { }
    private record Feature(String type, Point a, Point b, double radius, double falloff,
                           double height, List<Point> points) { }
    public record Tile(Region bounds, Map<BlockPos,String> blocks) { }

    public TerrainRecipe(JsonObject json) {
        fields(json,"version","min","max","base_height","seed","noise","mode","palette","features","preserve");
        if (integer(json,"version",1,1)!=1) throw invalid("Unsupported terrain version");
        bounds=new Region("terrain",pos(object(json,"min")),pos(object(json,"max")));
        if (width()>2048 || length()>2048 || height()>384 || (long)width()*length()>1_048_576
            || bounds.volume()>134_217_728) throw invalid("Terrain envelope exceeds 2048 per side, 384 height, 1M columns or 128M voxels");
        base=integer(json,"base_height",-4096,4096); seed=integer(json,"seed",Integer.MIN_VALUE,Integer.MAX_VALUE);
        mode=text(json,"mode"); if(!Set.of("sculpt","fill","cut").contains(mode))throw invalid("Mode must be sculpt, fill or cut");
        JsonObject noise=object(json,"noise");fields(noise,"amplitude","scale");
        amplitude=number(noise,"amplitude",0,256);scale=number(noise,"scale",1,4096);
        JsonObject palette=object(json,"palette");fields(palette,"rock","soil","surface","soil_depth");
        rock=material(palette,"rock");soil=material(palette,"soil");surface=material(palette,"surface");depth=integer(palette,"soil_depth",0,16);
        List<Feature> parsed=new ArrayList<>();
        for(JsonElement e:array(json,"features",64)) {
            if(!e.isJsonObject())throw invalid("Feature must be an object");
            JsonObject f=e.getAsJsonObject();String type=text(f,"type");
            switch(type) {
                case "hill", "basin" -> {
                    fields(f,"type","center","radius","height","falloff");
                    Point c=point(object(f,"center"));double r=number(f,"radius",1,2048);
                    parsed.add(new Feature(type,c,null,r,number(f,"falloff",1,2048),number(f,"height",-4096,4096),List.of()));
                }
                case "plateau" -> {
                    fields(f,"type","min","max","height","falloff");Point a=point(object(f,"min")),b=point(object(f,"max"));
                    if(a.x>b.x||a.z>b.z)throw invalid("Invalid plateau bounds");
                    parsed.add(new Feature(type,a,b,0,number(f,"falloff",1,2048),number(f,"height",-4096,4096),List.of()));
                }
                case "ridge", "channel" -> {
                    fields(f,"type","points","width","falloff","height");List<Point> points=new ArrayList<>();
                    for(JsonElement p:array(f,"points",32)) {if(!p.isJsonObject())throw invalid("Expected path point");points.add(point(p.getAsJsonObject()));}
                    if(points.size()<2)throw invalid("A path needs 2..32 points");
                    parsed.add(new Feature(type,null,null,number(f,"width",1,1024),number(f,"falloff",1,2048),number(f,"height",-4096,4096),List.copyOf(points)));
                }
                case "terrace" -> {
                    fields(f,"type","step","strength");
                    parsed.add(new Feature(type,null,null,number(f,"step",1,128),0,number(f,"strength",0,1),List.of()));
                }
                default -> throw invalid("Unsupported terrain feature: "+type);
            }
        }
        features=List.copyOf(parsed);List<Region> excluded=new ArrayList<>();
        for(JsonElement e:array(json,"preserve",64)) {
            if(!e.isJsonObject())throw invalid("Preserve box must be an object");JsonObject box=e.getAsJsonObject();fields(box,"min","max");
            Region r=new Region("terrain",pos(object(box,"min")),pos(object(box,"max")));
            if(!bounds.contains(r.min())||!bounds.contains(r.max()))throw invalid("Preserve box exceeds envelope");excluded.add(r);
        }
        preserves=List.copyOf(excluded);
        try { id=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical(json).toString().getBytes(StandardCharsets.UTF_8))); }
        catch(java.security.NoSuchAlgorithmException e){throw new AssertionError(e);}
    }
    public Region bounds(){return bounds;}
    public String id(){return id;}
    public String mode(){return mode;}
    public int width(){return bounds.max().x()-bounds.min().x()+1;}
    public int length(){return bounds.max().z()-bounds.min().z()+1;}
    public int height(){return bounds.max().y()-bounds.min().y()+1;}
    public boolean preserved(BlockPos at){return preserves.stream().anyMatch(r->r.contains(at));}
    public static boolean replaceable(String state) {
        String name=state.split("\\[",2)[0];return name.equals("minecraft:air") || name.equals("minecraft:cave_air")
            || name.equals("minecraft:void_air") || (name.startsWith("minecraft:") && MATERIALS.contains(name.substring(10)));
    }
    /** Unclamped surface. Layers use this height even across vertical tile boundaries. */
    public int surfaceHeight(int x,int z) {
        double h=base+amplitude*(noise(x/scale,z/scale)+0.5*noise(x/(scale/2),z/(scale/2))+0.25*noise(x/(scale/4),z/(scale/4)))/1.75;
        for(Feature f:features) {
            if(f.type.equals("terrace")){h=lerp(h,Math.floor(h/f.radius)*f.radius,f.height);continue;}
            double d;
            if(f.type.equals("plateau"))d=Math.hypot(Math.max(Math.max(f.a.x-x,0),x-f.b.x),Math.max(Math.max(f.a.z-z,0),z-f.b.z));
            else if(f.type.equals("hill")||f.type.equals("basin"))d=Math.max(0,Math.hypot(x-f.a.x,z-f.a.z)-f.radius);
            else {d=Double.POSITIVE_INFINITY;for(int i=1;i<f.points.size();i++)d=Math.min(d,segment(x,z,f.points.get(i-1),f.points.get(i)));d=Math.max(0,d-f.radius);}
            double w=1-smooth(Math.min(1,d/f.falloff));
            switch(f.type){
                case "hill","ridge" -> h+=f.height*w;
                case "basin","channel" -> h=lerp(h,Math.min(h,f.height),w);
                case "plateau" -> h=lerp(h,f.height,w);
                default -> throw new AssertionError(f.type);
            }
        }
        return (int)Math.floor(h);
    }
    private double noise(double x,double z){int ix=(int)Math.floor(x),iz=(int)Math.floor(z);return lerp(lerp(hash(ix,iz),hash(ix+1,iz),smooth(x-ix)),lerp(hash(ix,iz+1),hash(ix+1,iz+1),smooth(x-ix)),smooth(z-iz));}
    private double hash(int x,int z){long v=seed^((long)x*0x9E3779B97F4A7C15L)^((long)z*0xC2B2AE3D27D4EB4FL);v=(v^(v>>>30))*0xBF58476D1CE4E5B9L;v=(v^(v>>>27))*0x94D049BB133111EBL;v^=v>>>31;return (v>>>11)*0x1.0p-53*2-1;}
    private static double segment(double x,double z,Point a,Point b){double dx=b.x-a.x,dz=b.z-a.z,l=dx*dx+dz*dz;double t=l==0?0:Math.max(0,Math.min(1,((x-a.x)*dx+(z-a.z)*dz)/l));return Math.hypot(x-a.x-t*dx,z-a.z-t*dz);}
    private static double smooth(double t){return t*t*(3-2*t);}
    private static double lerp(double a,double b,double t){return a+(b-a)*t;}
    public int tileEdge(int limit){if(limit<1||limit>4096)throw invalid("Tile budget must be 1..4096");int e=1;while((e+1)*(e+1)*(e+1)<=limit&&e<16)e++;return e;}
    private static int ceil(int n,int d){return (n+d-1)/d;}
    public int tileCount(int limit){int e=tileEdge(limit);return Math.multiplyExact(Math.multiplyExact(ceil(width(),e),ceil(length(),e)),ceil(height(),e));}
    /** Tile index order: X fastest, then Z, then Y. Envelope minimum is the stable tiling origin. */
    public Tile tile(int index,int limit){
        int edge=tileEdge(limit),nx=ceil(width(),edge),nz=ceil(length(),edge);
        if(index<0||index>=tileCount(limit))throw invalid("Tile index outside terrain");
        BlockPos min=bounds.min().add(new BlockPos(index%nx*edge,index/(nx*nz)*edge,index/nx%nz*edge));
        BlockPos max=new BlockPos(Math.min(min.x()+edge-1,bounds.max().x()),Math.min(min.y()+edge-1,bounds.max().y()),Math.min(min.z()+edge-1,bounds.max().z()));
        Map<BlockPos,String> desired=new LinkedHashMap<>();
        for(int z=min.z();z<=max.z();z++)for(int x=min.x();x<=max.x();x++){
            int h=surfaceHeight(x,z);
            for(int y=min.y();y<=max.y();y++){
                if(mode.equals("fill")&&y>h || mode.equals("cut")&&y<=h)continue;
                BlockPos at=new BlockPos(x,y,z);if(preserved(at))continue;
                desired.put(at,y>h?"minecraft:air":y==h?surface:y>=h-depth?soil:rock);
            }
        }
        return new Tile(new Region("terrain",min,max),Collections.unmodifiableMap(desired));
    }
    private static String material(JsonObject o,String key){String s=text(o,key);if(!s.startsWith("minecraft:")||!MATERIALS.contains(s.substring(10)))throw invalid("Unsupported terrain material: "+s);return s;}
    private static Point point(JsonObject o){fields(o,"x","z");return new Point(integer(o,"x",-30_000_000,30_000_000),integer(o,"z",-30_000_000,30_000_000));}
    private static BlockPos pos(JsonObject o){fields(o,"x","y","z");return new BlockPos(integer(o,"x",-30_000_000,30_000_000),integer(o,"y",-4096,4096),integer(o,"z",-30_000_000,30_000_000));}
    private static JsonElement required(JsonObject o,String k){if(o==null||!o.has(k)||o.get(k).isJsonNull())throw invalid("Missing field: "+k);return o.get(k);}
    private static JsonObject object(JsonObject o,String k){JsonElement e=required(o,k);if(!e.isJsonObject())throw invalid(k+" must be an object");return e.getAsJsonObject();}
    private static JsonArray array(JsonObject o,String k,int max){JsonElement e=required(o,k);if(!e.isJsonArray()||e.getAsJsonArray().size()>max)throw invalid(k+" must be an array of at most "+max);return e.getAsJsonArray();}
    private static String text(JsonObject o,String k){JsonElement e=required(o,k);if(!e.isJsonPrimitive()||!e.getAsJsonPrimitive().isString())throw invalid(k+" must be text");return e.getAsString();}
    private static double number(JsonObject o,String k,double min,double max){JsonElement e=required(o,k);if(!e.isJsonPrimitive()||!e.getAsJsonPrimitive().isNumber())throw invalid(k+" must be numeric");double v=e.getAsDouble();if(!Double.isFinite(v)||v<min||v>max)throw invalid(k+" out of range");return v;}
    private static int integer(JsonObject o,String k,int min,int max){JsonElement e=required(o,k);if(!e.isJsonPrimitive()||!e.getAsJsonPrimitive().isNumber()||!e.getAsString().matches("-?(0|[1-9][0-9]*)"))throw invalid(k+" must be an integer");double v=number(o,k,min,max);return (int)v;}
    private static void fields(JsonObject o,String... keys){if(o==null)throw invalid("Expected object");Set<String> allowed=Set.of(keys);for(String k:o.keySet())if(!allowed.contains(k))throw invalid("Unknown field: "+k);}
    private static IllegalArgumentException invalid(String message){return new IllegalArgumentException(message);}
    private static JsonElement canonical(JsonElement e){if(e.isJsonObject()){JsonObject r=new JsonObject();new TreeSet<>(e.getAsJsonObject().keySet()).forEach(k->r.add(k,canonical(e.getAsJsonObject().get(k))));return r;}if(e.isJsonArray()){JsonArray a=new JsonArray();e.getAsJsonArray().forEach(v->a.add(canonical(v)));return a;}return e.deepCopy();}
}
