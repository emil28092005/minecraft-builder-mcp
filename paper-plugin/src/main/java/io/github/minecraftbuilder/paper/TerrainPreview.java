package io.github.minecraftbuilder.paper;

import io.github.minecraftbuilder.core.*;
import java.awt.image.BufferedImage;
import java.io.*;
import java.util.*;
import javax.imageio.ImageIO;

/** Diagram of the requested field, never presented as a capture or a live-world comparison. */
public final class TerrainPreview {
    private TerrainPreview() { }
    public static Map<String,Object> render(TerrainRecipe recipe,int resolution,int maxBlocks) throws IOException {
        if(resolution<32||resolution>256)throw new IllegalArgumentException("Resolution must be 32..256");
        int w=Math.min(resolution,recipe.width()),h=Math.min(resolution,recipe.length());
        int[][] heights=new int[h][w];int low=Integer.MAX_VALUE,high=Integer.MIN_VALUE,clipped=0;
        for(int z=0;z<h;z++)for(int x=0;x<w;x++){
            int value=recipe.surfaceHeight(coordinate(x,w,recipe.bounds().min().x(),recipe.width()),coordinate(z,h,recipe.bounds().min().z(),recipe.length()));
            heights[z][x]=value;low=Math.min(low,value);high=Math.max(high,value);
            if(value<recipe.bounds().min().y()||value>recipe.bounds().max().y())clipped++;
        }
        BufferedImage image=new BufferedImage(w*2,h*2,BufferedImage.TYPE_INT_RGB);
        for(int z=0;z<h;z++)for(int x=0;x<w;x++){
            double t=(heights[z][x]-low)/(double)Math.max(1,high-low);
            double slope=(heights[z][Math.max(0,x-1)]-heights[z][Math.min(w-1,x+1)])+(heights[Math.max(0,z-1)][x]-heights[Math.min(h-1,z+1)][x]);
            double shade=Math.max(0.55,Math.min(1.25,0.9+slope*0.035));
            int red=(int)((48+155*t)*shade),green=(int)((80+115*t)*shade),blue=(int)((65+107*t)*shade);
            int rgb=(Math.min(255,red)<<16)|(Math.min(255,green)<<8)|Math.min(255,blue);
            BlockPos at=new BlockPos(coordinate(x,w,recipe.bounds().min().x(),recipe.width()),Math.max(recipe.bounds().min().y(),Math.min(recipe.bounds().max().y(),heights[z][x])),coordinate(z,h,recipe.bounds().min().z(),recipe.length()));
            if(recipe.preserved(at))rgb=0xD696CD;
            for(int dz=0;dz<2;dz++)for(int dx=0;dx<2;dx++)image.setRGB(x*2+dx,z*2+dz,rgb);
        }
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();ImageIO.write(image,"png",bytes);
        return Map.ofEntries(Map.entry("status","completed"),Map.entry("kind","terrain_heightmap_preview"),
            Map.entry("terrain_id",recipe.id()),Map.entry("bounds",recipe.bounds()),Map.entry("mode",recipe.mode()),
            Map.entry("tile_edge",recipe.tileEdge(maxBlocks)),Map.entry("tile_count",recipe.tileCount(maxBlocks)),
            Map.entry("tile_order","x_then_z_then_y"),Map.entry("tile_budget",maxBlocks),
            Map.entry("sampled_height_min",low),Map.entry("sampled_height_max",high),Map.entry("clipped_samples",clipped),
            Map.entry("sample_grid",Map.of("width",w,"height",h)),Map.entry("orientation","north (-Z) up; east (+X) right"),
            Map.entry("legend","Dark green = low; pale stone = high; pink = preserved at sampled surface"),
            Map.entry("world_verified",false),Map.entry("note","Target surface only; no live world reads. Bounds clip writes, not height calculations. Cache holds 32 recipes until restart; save the recipe to regenerate the same ID."),
            Map.entry("mimeType","image/png"),Map.entry("imageBase64",Base64.getEncoder().encodeToString(bytes.toByteArray())));
    }
    private static int coordinate(int i,int count,int min,int length){return min+(int)((long)i*(length-1)/Math.max(1,count-1));}
    /** Offline preview using exactly the server compiler; args: recipe.json output.png metadata.json. */
    public static void main(String[] args) throws Exception {
        if(args.length!=3)throw new IllegalArgumentException("Usage: TerrainPreview recipe.json output.png metadata.json");
        TerrainRecipe recipe=new TerrainRecipe(com.google.gson.JsonParser.parseString(java.nio.file.Files.readString(java.nio.file.Path.of(args[0]))).getAsJsonObject());
        Map<String,Object> result=new LinkedHashMap<>(render(recipe,256,4096));
        java.nio.file.Files.write(java.nio.file.Path.of(args[1]),Base64.getDecoder().decode((String)result.remove("imageBase64")));
        java.nio.file.Files.writeString(java.nio.file.Path.of(args[2]),new com.google.gson.GsonBuilder().setPrettyPrinting().create().toJson(result));
    }
}
