package io.github.minecraftbuilder.core;

import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;
import java.util.*;
import java.util.function.IntBinaryOperator;
import static org.junit.jupiter.api.Assertions.*;

class TerrainBrushTest {
    static final Region BOX=new Region("world",new BlockPos(-4,-4,-4),new BlockPos(4,10,4));
    static TerrainBrush.Spec spec(String action,int amount,int height,double strength,double falloff){return new TerrainBrush.Spec(BOX,0,0,3,action,amount,height,strength,falloff,1,List.of());}
    static Map<BlockPos,String> snapshot(IntBinaryOperator height){Map<BlockPos,String> map=new LinkedHashMap<>();for(int y=-4;y<=10;y++)for(int z=-4;z<=4;z++)for(int x=-4;x<=4;x++){
        int h=height.applyAsInt(x,z);map.put(new BlockPos(x,y,z),y>h?"minecraft:air":y==h?"minecraft:grass_block[snowy=false]":y>=h-2?"minecraft:dirt":"minecraft:stone");
    }return map;}
    @Test void raiseAndLowerAreRelativeToEachOriginalColumnAndMoveSurface(){
        var snap=snapshot((x,z)->x/2+2);var up=TerrainBrush.compile(spec("raise",2,0,1,0),snap,4096);
        var down=TerrainBrush.compile(spec("lower",2,0,1,0),snap,4096);
        for(int z=-3;z<=3;z++)for(int x=-3;x<=3;x++)if(x*x+z*z<=9){
            int h=x/2+2;assertEquals(h+2,up.after()[z+4][x+4]);assertEquals(h-2,down.after()[z+4][x+4]);
            assertEquals("minecraft:grass_block[snowy=false]",up.desired().get(new BlockPos(x,h+2,z)));
            assertEquals("minecraft:dirt",up.desired().get(new BlockPos(x,h,z)));
            assertEquals("minecraft:air",down.desired().get(new BlockPos(x,h,z)));
        }
        assertEquals(snap.keySet(),up.dependencies());assertEquals(1215,up.dependencies().size());
    }
    @Test void softFalloffAndStrengthAreSymmetricAndLeaveEdgeUntouched(){
        var snap=snapshot((x,z)->3);var up=TerrainBrush.compile(spec("raise",4,0,.5,1),snap,4096);var down=TerrainBrush.compile(spec("lower",4,0,.5,1),snap,4096);
        assertEquals(5,up.after()[4][4]);assertEquals(1,down.after()[4][4]);assertEquals(3,up.after()[4][7]);
        for(int z=0;z<9;z++)for(int x=0;x<9;x++)assertEquals(up.after()[z][x]-3,3-down.after()[z][x]);
        assertTrue(TerrainBrush.compile(spec("raise",4,0,0,.5),snap,4096).desired().isEmpty());
    }
    @Test void flattenUsesAbsoluteLevelAndSmoothUsesImmutableHalo(){
        var snap=snapshot((x,z)->x==0&&z==0?8:2);
        var flat=TerrainBrush.compile(spec("flatten",1,4,1,0),snap,4096);assertEquals(4,flat.after()[4][4]);assertEquals(4,flat.after()[4][5]);
        var smooth=TerrainBrush.compile(spec("smooth",1,0,1,0),snap,4096);
        assertEquals(3,smooth.after()[4][4]);assertEquals(3,smooth.after()[4][5]);assertEquals(3,smooth.after()[4][3]);
        assertEquals(2,smooth.after()[4][6]);
        var reversed=new LinkedHashMap<BlockPos,String>();var entries=new ArrayList<>(snap.entrySet());Collections.reverse(entries);entries.forEach(e->reversed.put(e.getKey(),e.getValue()));
        assertEquals(smooth.desired(),TerrainBrush.compile(spec("smooth",1,0,1,0),reversed,4096).desired());
    }
    @Test void preserveSkipsTheWholeAffectedColumn(){
        var b=spec("raise",2,0,1,0);var s=new TerrainBrush.Spec(BOX,0,0,3,"raise",2,0,1,0,1,List.of(new Region("world",new BlockPos(0,3,0),new BlockPos(0,3,0))));
        var result=TerrainBrush.compile(s,snapshot((x,z)->2),4096);
        assertEquals(2,result.after()[4][4]);assertFalse(result.desired().keySet().stream().anyMatch(p->p.x()==0&&p.z()==0));assertEquals(4,result.after()[4][5]);
    }
    @Test void refusesAmbiguousSurfacesStructuresFluidsVoidsAndClipping(){
        for(String state:List.of("minecraft:gold_block","minecraft:water","minecraft:bedrock","minecraft:oak_log")){
            var snap=snapshot((x,z)->2);snap.put(new BlockPos(0,2,0),state);assertThrows(IllegalArgumentException.class,()->TerrainBrush.compile(spec("raise",1,0,1,0),snap,4096));
        }
        assertThrows(IllegalArgumentException.class,()->TerrainBrush.compile(spec("raise",1,0,1,0),snapshot((x,z)->10),4096));
        assertThrows(IllegalArgumentException.class,()->TerrainBrush.compile(spec("raise",1,0,1,0),snapshot((x,z)->-5),4096));
        assertThrows(IllegalArgumentException.class,()->TerrainBrush.compile(spec("raise",20,0,1,0),snapshot((x,z)->2),4096));
        var cave=snapshot((x,z)->2);cave.put(new BlockPos(0,0,0),"minecraft:cave_air");assertThrows(IllegalArgumentException.class,()->TerrainBrush.compile(spec("lower",2,0,1,0),cave,4096));
        assertThrows(IllegalArgumentException.class,()->TerrainBrush.compile(spec("raise",2,0,1,0),snapshot((x,z)->2),1));
    }
    @Test void validatesHaloScanBudgetAndActionSpecificFields(){
        assertThrows(IllegalArgumentException.class,()->new TerrainBrush.Spec(BOX,0,0,4,"smooth",1,0,1,0,1,List.of()));
        assertThrows(IllegalArgumentException.class,()->new TerrainBrush.Spec(new Region("w",new BlockPos(-20,-20,-20),new BlockPos(20,20,20)),0,0,3,"raise",1,0,1,0,1,List.of()));
        String base="\"min\":{\"x\":-4,\"y\":-4,\"z\":-4},\"max\":{\"x\":4,\"y\":10,\"z\":4},\"center\":{\"x\":0,\"z\":0},\"radius\":3,";
        for(String tail:List.of("\"action\":\"raise\"","\"action\":\"flatten\"","\"action\":\"smooth\",\"amount\":2","\"action\":\"raise\",\"amount\":2,\"height\":3","\"action\":\"raise\",\"amount\":2,\"script\":\"bad\""))assertThrows(IllegalArgumentException.class,()->TerrainBrush.parse(JsonParser.parseString("{"+base+tail+"}").getAsJsonObject()));
    }
    @Test void realEngineAppliesAndUndoesBrushWithAllSnapshotDependencies() throws Exception {
        var original=snapshot((x,z)->2);var world=new EditEngineTest.MemoryWorld();world.blocks.putAll(original);
        var engine=new EditEngine(world,s->true,p->{},new EditEngineTest.MemoryJournal(),new Limits(4096,4096,128,1_000_000_000,600000,8));
        var brush=TerrainBrush.compile(spec("raise",2,0,1,.5),original,4096);
        var plan=engine.prepare("project","epoch",BOX,brush.desired(),brush.dependencies());engine.persistPlan(plan.id());
        String id=EditEngineTest.start(engine,plan);assertEquals(OperationStatus.APPLIED,EditEngineTest.finish(engine,id).status());
        brush.desired().forEach((p,s)->assertEquals(s,world.getBlock(p)));
        var undo=engine.prepareUndo(id);engine.persistPlan(undo.id());assertEquals(OperationStatus.APPLIED,EditEngineTest.finish(engine,EditEngineTest.start(engine,undo)).status());assertEquals(original,world.blocks);
    }
    @Test void haloEditDuringJournalIoStopsBeforeAnyBrushWrite() throws Exception {
        var original=snapshot((x,z)->2);var world=new EditEngineTest.MemoryWorld();world.blocks.putAll(original);
        var engine=new EditEngine(world,s->true,p->{},new EditEngineTest.MemoryJournal(),new Limits(4096,4096,128,1_000_000_000,600000,8));
        var brush=TerrainBrush.compile(spec("smooth",1,0,1,0),snapshot((x,z)->x==0&&z==0?8:2),4096);
        // Engine must capture the exact same source that produced the smoothing result.
        world.blocks.clear();world.blocks.putAll(snapshot((x,z)->x==0&&z==0?8:2));
        var plan=engine.prepare("project","epoch",BOX,brush.desired(),brush.dependencies());engine.persistPlan(plan.id());String id=EditEngineTest.start(engine,plan);
        var intent=EditEngineTest.nextIntent(engine,id);engine.persistIntent(intent);
        BlockPos halo=new BlockPos(4,3,0);assertFalse(brush.desired().containsKey(halo));world.blocks.put(halo,"minecraft:gold_block");
        assertEquals(OperationStatus.CONFLICT,engine.commitSlice(intent).status());assertEquals(0,world.writes);
    }
}
