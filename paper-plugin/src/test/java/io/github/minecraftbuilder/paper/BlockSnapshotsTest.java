package io.github.minecraftbuilder.paper;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

final class BlockSnapshotsTest {
    @Test void payloadSurvivesExactlyButPublicViewOnlyContainsStateAndDigest() {
        String state = "minecraft:chest[facing=north,type=single,waterlogged=false]";
        String nbt = "{Items:[{id:\"minecraft:written_book\",components:{text:\"private secret\"}}],id:\"minecraft:chest\"}";
        String encoded = BlockSnapshots.encode(state, nbt);
        assertEquals(state, BlockSnapshots.state(encoded));
        assertEquals(nbt, BlockSnapshots.decode(encoded).nbt());
        var publicValue = BlockSnapshots.publicView(encoded);
        assertEquals(2, publicValue.size());
        assertEquals(state, publicValue.get("state"));
        assertTrue(publicValue.get("snapshot_id").matches("[0-9a-f]{64}"));
        assertFalse(publicValue.toString().contains("private secret"));
        assertNotEquals(BlockSnapshots.snapshotId(encoded), BlockSnapshots.snapshotId(BlockSnapshots.encode(state, nbt + " ")));
        assertEquals(publicValue, BlockSnapshots.publicView(encoded));
    }
    @Test void oldPlainJournalStatesStayUnchanged() {
        String plain = "minecraft:stone";
        assertEquals(plain, BlockSnapshots.decode(plain).state());
        assertNull(BlockSnapshots.decode(plain).nbt());
        assertNull(BlockSnapshots.snapshotId(plain));
        assertEquals(java.util.Map.of("state", plain), BlockSnapshots.publicView(plain));
    }
    @Test void entityBudgetCountsUtf8BytesAndErrorsNeverIncludePrivateText() {
        String huge = "секрет".repeat(BlockSnapshots.MAX_SNAPSHOT_BYTES / 7);
        var error = assertThrows(IllegalArgumentException.class, () -> BlockSnapshots.encode("minecraft:chest", huge));
        assertTrue(error.getMessage().contains("snapshot_budget_exceeded"));
        assertFalse(error.getMessage().contains("секрет"));
    }
    @Test void malformedKnownSnapshotAndAmbiguousStateAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> BlockSnapshots.decode("\u0000mcb-block-v1:minecraft:chest"));
        assertThrows(IllegalArgumentException.class, () -> BlockSnapshots.encode("minecraft:chest\n{}", "{}"));
    }
}
