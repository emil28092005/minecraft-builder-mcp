package io.github.minecraftbuilder.paper;

import com.google.gson.JsonParser;
import io.github.minecraftbuilder.core.TerrainRecipe;
import org.junit.jupiter.api.Test;
import java.io.ByteArrayInputStream;
import java.util.Base64;
import javax.imageio.ImageIO;
import static org.junit.jupiter.api.Assertions.*;

class TerrainPreviewTest {
    @Test void previewIsBoundedNativePngAndReportsClippingWithoutClaimingWorldVerification() throws Exception {
        var recipe=new TerrainRecipe(JsonParser.parseString("""
          {"version":1,"min":{"x":0,"y":0,"z":0},"max":{"x":7,"y":7,"z":7},
          "base_height":20,"seed":1,"mode":"sculpt","noise":{"amplitude":0,"scale":8},
          "palette":{"rock":"minecraft:stone","soil":"minecraft:dirt","surface":"minecraft:grass_block","soil_depth":2},"features":[],"preserve":[]}
          """).getAsJsonObject());
        var result=TerrainPreview.render(recipe,32,4096);
        assertEquals(false,result.get("world_verified"));assertEquals(64,result.get("clipped_samples"));assertEquals(1,result.get("tile_count"));
        var image=ImageIO.read(new ByteArrayInputStream(Base64.getDecoder().decode((String)result.get("imageBase64"))));
        assertEquals(16,image.getWidth());assertEquals(16,image.getHeight());
        assertThrows(IllegalArgumentException.class,()->TerrainPreview.render(recipe,1024,4096));
    }
}
