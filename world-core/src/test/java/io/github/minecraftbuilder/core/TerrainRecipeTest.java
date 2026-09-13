package io.github.minecraftbuilder.core;

import com.google.gson.*;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class TerrainRecipeTest {
    static JsonObject json(){return JsonParser.parseString("""
        {"version":1,"min":{"x":-17,"y":-4,"z":-17},"max":{"x":17,"y":20,"z":17},
         "base_height":5,"seed":123,"mode":"sculpt","noise":{"amplitude":0,"scale":24},
         "palette":{"rock":"minecraft:stone","soil":"minecraft:dirt","surface":"minecraft:grass_block","soil_depth":2},
         "features":[],"preserve":[]}
        """).getAsJsonObject();}
    static TerrainRecipe feature(String features){var j=json();j.add("features",JsonParser.parseString(features));return new TerrainRecipe(j);}
    static Map<BlockPos,String> all(TerrainRecipe r,int budget){Map<BlockPos,String> result=new HashMap<>();for(int i=0;i<r.tileCount(budget);i++){
        var tile=r.tile(i,budget);assertTrue(tile.bounds().volume()<=budget);assertTrue(tile.blocks().size()<=budget);
        tile.blocks().forEach((p,s)->{assertTrue(r.bounds().contains(p));assertNull(result.put(p,s),"overlapping tile at "+p);});
    }return result;}
    @Test void tilingHasNoGapsOverlapsOrSeamsIncludingNegativeCoordinatesAndVerticalLayers(){
        var j=json();j.getAsJsonObject("noise").addProperty("amplitude",4);var r=new TerrainRecipe(j);
        var a=all(r,4096);var b=all(r,512);assertEquals(r.bounds().volume(),a.size());assertEquals(a,b);
        for(int z=-17;z<=17;z++)for(int x=-17;x<=17;x++){
            int h=r.surfaceHeight(x,z);assertEquals("minecraft:grass_block",a.get(new BlockPos(x,h,z)));
            assertEquals("minecraft:dirt",a.get(new BlockPos(x,h-2,z)));assertEquals("minecraft:stone",a.get(new BlockPos(x,h-3,z)));
            assertEquals("minecraft:air",a.get(new BlockPos(x,h+1,z)));
        }
    }
    @Test void deterministicSeedAndWorldCoordinatesIndependentOfEnvelope(){
        var j=json();j.getAsJsonObject("noise").addProperty("amplitude",20);var a=new TerrainRecipe(j);var b=new TerrainRecipe(j.deepCopy());
        assertEquals(a.id(),b.id());j.getAsJsonObject("min").addProperty("x",-9);var cropped=new TerrainRecipe(j);
        for(int z=-9;z<=9;z++)for(int x=-9;x<=9;x++)assertEquals(a.surfaceHeight(x,z),cropped.surfaceHeight(x,z));
        j.addProperty("seed",124);var other=new TerrainRecipe(j);assertNotEquals(a.id(),other.id());
        assertTrue(java.util.stream.IntStream.range(-8,9).anyMatch(x->a.surfaceHeight(x,7)!=other.surfaceHeight(x,7)));
    }
    @Test void hashIgnoresObjectKeyOrderButPreservesFeatureOrder(){
        var j=json();var reversed=new JsonObject();var keys=new ArrayList<>(j.keySet());Collections.reverse(keys);keys.forEach(k->reversed.add(k,j.get(k)));
        assertEquals(new TerrainRecipe(j).id(),new TerrainRecipe(reversed).id());
    }
    @Test void plateauBlendsOnlyOutsideItsFootprintAndOrderMatters(){
        var r=feature("""
          [{"type":"plateau","min":{"x":-2,"z":-2},"max":{"x":2,"z":2},"height":13,"falloff":4}]
          """);
        assertEquals(13,r.surfaceHeight(0,0));assertEquals(13,r.surfaceHeight(2,2));assertEquals(9,r.surfaceHeight(4,0));assertEquals(5,r.surfaceHeight(6,0));
        var later=feature("""
          [{"type":"hill","center":{"x":0,"z":0},"radius":1,"height":10,"falloff":4},
           {"type":"plateau","min":{"x":-2,"z":-2},"max":{"x":2,"z":2},"height":8,"falloff":2}]
          """);assertEquals(8,later.surfaceHeight(0,0));
    }
    @Test void hillAndRidgeAddAndFallOffContinuously(){
        var hill=feature("""
[{"type":"hill","center":{"x":0,"z":0},"radius":2,"height":8,"falloff":4}]
""");
        assertEquals(13,hill.surfaceHeight(0,0));assertEquals(9,hill.surfaceHeight(4,0));assertEquals(5,hill.surfaceHeight(6,0));
        var ridge=feature("""
[{"type":"ridge","points":[{"x":-4,"z":0},{"x":4,"z":0}],"width":2,"height":8,"falloff":4}]
""");
        assertEquals(13,ridge.surfaceHeight(0,0));assertEquals(9,ridge.surfaceHeight(0,4));assertEquals(5,ridge.surfaceHeight(0,6));
    }
    @Test void basinAndChannelOnlyLowerAndHandleRepeatedPoints(){
        var basin=feature("""
[{"type":"basin","center":{"x":0,"z":0},"radius":2,"height":-3,"falloff":4}]
""");
        assertEquals(-3,basin.surfaceHeight(0,0));assertEquals(1,basin.surfaceHeight(4,0));assertEquals(5,basin.surfaceHeight(6,0));
        var high=feature("""
[{"type":"basin","center":{"x":0,"z":0},"radius":2,"height":20,"falloff":4}]
""");assertEquals(5,high.surfaceHeight(0,0));
        var channel=feature("""
[{"type":"channel","points":[{"x":0,"z":0},{"x":0,"z":0},{"x":8,"z":0}],"width":2,"height":-3,"falloff":4}]
""");assertEquals(-3,channel.surfaceHeight(4,0));assertEquals(1,channel.surfaceHeight(4,4));
    }
    @Test void terracesUseFloorForNegativeElevations(){
        var j=json();j.addProperty("base_height",-1);j.add("features",JsonParser.parseString("""
[{"type":"terrace","step":4,"strength":1}]
"""));
        assertEquals(-4,new TerrainRecipe(j).surfaceHeight(0,0));
    }
    @Test void modeAndPreserveMasksNeverLeakAcrossTiles(){
        var j=json();j.add("preserve",JsonParser.parseString("""
[{"min":{"x":-1,"y":0,"z":-1},"max":{"x":1,"y":9,"z":1}}]
"""));
        var r=new TerrainRecipe(j);var sculpt=all(r,4096);assertEquals(r.bounds().volume()-90,sculpt.size());assertFalse(sculpt.containsKey(new BlockPos(0,5,0)));
        j.addProperty("mode","fill");var fill=all(new TerrainRecipe(j),4096);assertTrue(fill.keySet().stream().allMatch(p->p.y()<=5));
        j.addProperty("mode","cut");var cut=all(new TerrainRecipe(j),4096);assertTrue(cut.values().stream().allMatch(s->s.equals("minecraft:air")));assertTrue(cut.keySet().stream().allMatch(p->p.y()>5));
        var both=new HashMap<>(fill);both.putAll(cut);assertEquals(sculpt,both);
    }
    @Test void malformedOrExpensiveRecipesRejectedBeforeExpansion(){
        var j=json();j.addProperty("script","bad");assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(j));
        for(String path:List.of("version","seed","base_height")){var n=json();n.addProperty(path,1.5);assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(n));}
        var big=json();big.getAsJsonObject("max").addProperty("x",30000000);assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(big));
        var wet=json();wet.getAsJsonObject("palette").addProperty("rock","minecraft:water");assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(wet));
        var empty=json();empty.add("features",JsonParser.parseString("""
[{"type":"channel","points":[],"width":1,"height":0,"falloff":1}]
"""));assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(empty));
        assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(json()).tile(-1,4096));assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(json()).tile(99999,4096));
        assertThrows(IllegalArgumentException.class,()->new TerrainRecipe(json()).tile(0,0));
    }
    @Test void naturalPolicyProtectsStructuresAndBedrock(){
        assertTrue(TerrainRecipe.replaceable("minecraft:grass_block[snowy=false]"));assertTrue(TerrainRecipe.replaceable("minecraft:air"));
        for(String s:List.of("bedrock","stone_bricks","oak_planks","water","chest","gold_block"))assertFalse(TerrainRecipe.replaceable("minecraft:"+s));
    }
    @Test void terrainPlanUsesRealJournalConflictChecksAndCheckedUndo() throws Exception {
        var world=new EditEngineTest.MemoryWorld();var journal=new EditEngineTest.MemoryJournal();
        var engine=new EditEngine(world,s->true,p->{},journal,new Limits(4096,16,128,1_000_000_000,600000,4));
        var j=json();j.add("max",JsonParser.parseString("{\"x\":-14,\"y\":0,\"z\":-14}"));var r=new TerrainRecipe(j);
        var desired=r.tile(0,4096).blocks();var plan=engine.prepare("project","epoch",EditEngineTest.REGION,desired,Set.of());engine.persistPlan(plan.id());
        String id=EditEngineTest.start(engine,plan);assertEquals(OperationStatus.APPLIED,EditEngineTest.finish(engine,id).status());
        desired.forEach((p,s)->assertEquals(s,world.getBlock(p)));
        var undo=engine.prepareUndo(id);engine.persistPlan(undo.id());assertEquals(OperationStatus.APPLIED,EditEngineTest.finish(engine,EditEngineTest.start(engine,undo)).status());
        desired.keySet().forEach(p->assertEquals("minecraft:air",world.getBlock(p)));
        var stale=engine.prepare("project","epoch",EditEngineTest.REGION,desired,Set.of());engine.persistPlan(stale.id());
        var edited=desired.keySet().iterator().next();world.blocks.put(edited,"minecraft:gold_block");world.writes=0;
        assertEquals(OperationStatus.CONFLICT,EditEngineTest.finish(engine,EditEngineTest.start(engine,stale)).status());assertEquals(0,world.writes);
    }
}
