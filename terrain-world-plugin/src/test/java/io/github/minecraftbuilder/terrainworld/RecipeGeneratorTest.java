package io.github.minecraftbuilder.terrainworld;

import com.google.gson.*;
import org.bukkit.Material;
import org.bukkit.generator.ChunkGenerator.ChunkData;
import org.junit.jupiter.api.Test;
import java.lang.reflect.Proxy;
import java.nio.file.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class RecipeGeneratorTest {
    private JsonObject naturalSource() throws Exception {
        return JsonParser.parseString(Files.readString(Path.of("../examples/terrain/shacraft-natural-world.json"))).getAsJsonObject();
    }
    @Test void productionFieldExactlyMatchesTheApprovedStudy() throws Exception {
        var terrain = new NaturalTerrain(28092005);
        var digest = java.security.MessageDigest.getInstance("SHA-256");
        var buffer = java.nio.ByteBuffer.allocate(4);
        for(int z=-384;z<384;z++)for(int x=-384;x<384;x++) {
            float h=terrain.height(x,z);
            assertTrue(h>=16&&h<=239);
            buffer.clear();buffer.putFloat(h);digest.update(buffer.array());
        }
        assertEquals("3ac6a3d8d884adf8ef074ec0dd4c0e066b18832f45a50e771b6d9433e4c79096",HexFormat.of().formatHex(digest.digest()));
    }
    @Test void naturalCliffsHaveRockInsteadOfSoilStripes() throws Exception {
        var generator=new RecipeGenerator(naturalSource(),48,"shacraft-natural-v1");
        var terrain=new NaturalTerrain(28092005);
        var cells=chunk(generator,-18,-19);
        int cliffs=0;
        for(int x=0;x<16;x++)for(int z=0;z<16;z++) {
            int wx=-288+x,wz=-304+z,top=generator.height(wx,wz);
            if(terrain.slope(wx,wz)>1.5) {
                cliffs++;
                assertTrue(Set.of(Material.STONE,Material.ANDESITE).contains(cells[x][top+64][z]));
                for(int y=top-3;y<top;y++)assertEquals(Material.STONE,cells[x][y+64][z]);
            }
        }
        assertTrue(cliffs>20);
        assertEquals(Material.GRASS_BLOCK,generator.surfaceMaterial(0,0));
    }
    @Test void naturalLakeHasContinuousWaterAndNoGrassUnderwater() throws Exception {
        var generator=new RecipeGenerator(naturalSource(),48,"shacraft-natural-v1");
        var cells=chunk(generator,-14,-1);
        for(int x=0;x<16;x++)for(int z=0;z<16;z++) {
            int top=generator.height(-224+x,-16+z);
            assertTrue(top<48);
            assertTrue(Set.of(Material.STONE,Material.ANDESITE).contains(cells[x][top+64][z]));
            for(int y=top+1;y<=48;y++)assertEquals(Material.WATER,cells[x][y+64][z]);
            assertNull(cells[x][49+64][z]);
        }
    }
    @Test void profileAndWaterArePartOfImmutableGenerationIdentity() throws Exception {
        var source=naturalSource();
        var dry=new RecipeGenerator(source,null,"shacraft-natural-v1");
        var wet=new RecipeGenerator(source,48,"shacraft-natural-v1");
        assertNotEquals(dry.identity(),wet.identity());
        assertNotEquals(wet.identity(),new RecipeGenerator(source,48).identity());
        assertThrows(IllegalArgumentException.class,()->new RecipeGenerator(source,48,"unknown"));
        assertThrows(IllegalArgumentException.class,()->new RecipeGenerator(source(),48,"shacraft-natural-v1"));
    }
    private JsonObject source() throws Exception {
        return JsonParser.parseString(Files.readString(Path.of("../examples/terrain/shacraft-lobby-world.json"))).getAsJsonObject();
    }
    private Material[][][] chunk(RecipeGenerator generator, int cx, int cz) {
        Material[][][] cells = new Material[16][384][16];
        ChunkData data = (ChunkData) Proxy.newProxyInstance(ChunkData.class.getClassLoader(), new Class[]{ChunkData.class}, (p, m, args) -> {
            switch (m.getName()) {
                case "getMinHeight": return -64;
                case "getMaxHeight": return 320;
                case "setBlock": cells[(int)args[0]][(int)args[1]+64][(int)args[2]] = (Material)args[3]; return null;
                case "setRegion":
                    for(int x=(int)args[0];x<(int)args[3];x++) for(int y=(int)args[1];y<(int)args[4];y++) for(int z=(int)args[2];z<(int)args[5];z++)
                        cells[x][y+64][z]=(Material)args[6];
                    return null;
                default: throw new UnsupportedOperationException(m.getName());
            }
        });
        generator.generateNoise(null, new Random(1), cx, cz, data);
        return cells;
    }
    @Test void spawnPlateauHasSolidFoundationAndDrySurface() throws Exception {
        var generator = new RecipeGenerator(source(), 48);
        var cells = chunk(generator, 0, 0);
        assertEquals(106, generator.height(0, 0));
        assertEquals(Material.BEDROCK, cells[0][0][0]);
        assertEquals(Material.STONE, cells[0][64][0]);
        assertEquals(Material.DIRT, cells[0][169][0]);
        assertEquals(Material.GRASS_BLOCK, cells[0][170][0]);
        assertNull(cells[0][171][0]);
    }
    @Test void westernLakeHasRockBedAndSourceWaterWithoutGaps() throws Exception {
        var generator = new RecipeGenerator(source(), 48);
        var cells = chunk(generator, -14, -1);
        int x = Math.floorMod(-220,16), z = Math.floorMod(-5,16);
        assertEquals(38, generator.height(-220,-5));
        assertEquals(Material.STONE,cells[x][38+64][z]);
        for(int y=39;y<=48;y++) assertEquals(Material.WATER,cells[x][y+64][z]);
        assertNull(cells[x][49+64][z]);
        assertEquals(48,generator.visibleHeight(-220,-5));
        assertEquals(38,new RecipeGenerator(source()).visibleHeight(-220,-5));
    }
    @Test void neighboringNegativeChunksMatchTheGlobalField() throws Exception {
        var generator = new RecipeGenerator(source(),48);
        for(int cx=-2;cx<=-1;cx++) {
            var cells=chunk(generator,cx,-18);
            for(int x=0;x<16;x++)for(int z=0;z<16;z++) {
                int top=generator.visibleHeight(cx*16+x,-18*16+z);
                assertNotNull(cells[x][top+64][z]);
                assertNull(cells[x][top+65][z]);
                for(int y=-64;y<top;y++)assertNotNull(cells[x][y+64][z]);
            }
        }
    }
    @Test void entireLobbyFitsWorldAndRetainsBuildingPads() throws Exception {
        var generator = new RecipeGenerator(source(),48);
        int low=320,high=-64;
        for(int x=-384;x<384;x++)for(int z=-384;z<384;z++) {
            int h=generator.height(x,z);low=Math.min(low,h);high=Math.max(high,h);
            assertTrue(h>=16&&h<=207,"Recipe clips at "+x+","+z);
        }
        assertEquals(22,low);
        assertTrue(high>150);
        assertEquals(118,generator.height(0,-120));
        assertEquals(124,generator.height(180,-140));
    }
    @Test void cutOrPreservedRecipesCannotGenerateNewWorlds() throws Exception {
        var source=source();source.addProperty("mode","cut");
        assertThrows(IllegalArgumentException.class,()->new RecipeGenerator(source));
    }
}
