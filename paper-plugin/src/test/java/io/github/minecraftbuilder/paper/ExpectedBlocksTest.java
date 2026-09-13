package io.github.minecraftbuilder.paper;

import com.google.gson.*;
import io.github.minecraftbuilder.core.BlockPos;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

class ExpectedBlocksTest {
    private final BlockPos a = new BlockPos(0,64,0), b = new BlockPos(1,64,0);
    private JsonArray entries(String... states) {
        JsonArray result=new JsonArray();
        for(int x=0;x<states.length;x++) {
            JsonObject e=new JsonObject(),p=new JsonObject();
            p.addProperty("x",x);p.addProperty("y",64);p.addProperty("z",0);
            e.add("pos",p);e.addProperty("state",states[x]);result.add(e);
        }
        return result;
    }
    @Test void rejectsManualChangeBetweenCallerReadAndPreparation() {
        var snapshot=entries("minecraft:grass_block","minecraft:air");
        var live=new HashMap<>(Map.of(a,"minecraft:grass_block",b,"minecraft:air"));
        ExpectedBlocks.check(snapshot,Set.of(a,b),s->s,live::get);
        live.put(b,"minecraft:gold_block");
        var error=assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(snapshot,Set.of(a,b),s->s,live::get));
        assertTrue(error.getMessage().contains("Caller snapshot changed"));
        assertEquals("minecraft:gold_block",live.get(b));
    }
    @Test void rejectsIncompleteDuplicateAndOutsideSnapshots() {
        assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(entries("air"),Set.of(a,b),s->s,p->"air"));
        var duplicate=entries("air","air");duplicate.set(1,duplicate.get(0));
        assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(duplicate,Set.of(a,b),s->s,p->"air"));
        assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(entries("air","air"),Set.of(a,new BlockPos(2,64,0)),s->s,p->"air"));
    }
    @Test void canonicalizesExpectedStatesAndRejectsFractionalCoordinates() {
        ExpectedBlocks.check(entries("grass_block"),Set.of(a),s->"minecraft:"+s,p->"minecraft:grass_block");
        var fractional=entries("air");fractional.get(0).getAsJsonObject().getAsJsonObject("pos").addProperty("x",.5);
        assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(fractional,Set.of(a),s->s,p->"air"));
    }
    @Test void detectsContentsChangeEvenWhenBlockStateIsUnchanged() {
        var snapshot=entries("minecraft:chest");
        snapshot.get(0).getAsJsonObject().addProperty("snapshot_id","a".repeat(64));
        ExpectedBlocks.check(snapshot,Set.of(a),s->s,p->"minecraft:chest",p->"a".repeat(64));
        var changed=assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(snapshot,Set.of(a),s->s,p->"minecraft:chest",p->"b".repeat(64)));
        assertTrue(changed.getMessage().contains("block-entity snapshot changed"));
        assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(snapshot,Set.of(a),s->s,p->"minecraft:chest",p->null));
    }
    @Test void requiresEntityDigestAndRejectsMalformedDigest() {
        var snapshot=entries("minecraft:chest");
        assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(snapshot,Set.of(a),s->s,p->"minecraft:chest",p->"a".repeat(64)));
        snapshot.get(0).getAsJsonObject().addProperty("snapshot_id","not-a-hash");
        assertThrows(RpcServer.Fault.class,()->ExpectedBlocks.check(snapshot,Set.of(a),s->s,p->"minecraft:chest",p->"a".repeat(64)));
    }
}
