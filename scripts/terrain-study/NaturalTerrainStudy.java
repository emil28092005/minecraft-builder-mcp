import com.google.gson.JsonParser;
import io.github.minecraftbuilder.core.TerrainRecipe;
import java.io.*;
import java.nio.file.*;

/** Offline composition experiment, not a world writer or a production recipe. */
public final class NaturalTerrainStudy {
    private static final io.github.minecraftbuilder.terrainworld.NaturalTerrain terrain =
        new io.github.minecraftbuilder.terrainworld.NaturalTerrain(28092005);
    static float height(int x,int z) { return terrain.height(x,z); }
    public static void main(String[] args) throws Exception {
        var old=new TerrainRecipe(JsonParser.parseString(Files.readString(Path.of(args[0]))).getAsJsonObject());
        Path output=Path.of(args[1]);Files.createDirectories(output);
        try(var a=new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(output.resolve("before.f32"))));
            var b=new DataOutputStream(new BufferedOutputStream(Files.newOutputStream(output.resolve("natural.f32"))))) {
            for(int z=-384;z<384;z++)for(int x=-384;x<384;x++) {a.writeFloat(old.surfaceHeight(x,z));b.writeFloat(height(x,z));}
        }
    }
}
