package io.github.minecraftbuilder.paper;

import io.github.minecraftbuilder.core.*;
import org.junit.jupiter.api.Test;
import java.util.*;
import java.io.ByteArrayInputStream;
import javax.imageio.ImageIO;
import static org.junit.jupiter.api.Assertions.*;

class BrushPreviewTest {
    @Test void nativePreviewShowsActualBeforeAfterWithoutWorldWriteClaim() throws Exception {
        var r=new TerrainBrush.Result(Map.of(new BlockPos(0,2,0),"minecraft:stone"),Set.of(new BlockPos(0,1,0)),
            new Region("world",new BlockPos(0,0,0),new BlockPos(1,3,1)),new int[][]{{1,1},{1,1}},new int[][]{{2,1},{0,1}},2,1,1);
        var result=BrushPreview.render(r);assertEquals("live_snapshot",result.get("source"));assertEquals(false,result.get("world_edited"));
        var image=ImageIO.read(new ByteArrayInputStream(Base64.getDecoder().decode((String)result.get("imageBase64"))));
        assertEquals(780,image.getWidth());assertEquals(300,image.getHeight());
        assertNotEquals(image.getRGB(10,40),image.getRGB(270,40));
        assertEquals(0x89CC70,image.getRGB(530,40)&0xFFFFFF);assertEquals(0xE5A35B,image.getRGB(530,160)&0xFFFFFF);
    }
}
