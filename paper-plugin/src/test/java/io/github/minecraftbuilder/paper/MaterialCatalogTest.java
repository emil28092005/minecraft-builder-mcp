package io.github.minecraftbuilder.paper;

import com.google.gson.Gson;
import org.junit.jupiter.api.Test;

import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.*;

class MaterialCatalogTest {
    private static List<MaterialCatalog.Entry> fixtures() {
        List<MaterialCatalog.Entry> entries = new ArrayList<>();
        IntStream.range(0, 70).forEach(i -> entries.add(new MaterialCatalog.Entry("minecraft:block_%02d".formatted(i), true, true)));
        entries.add(new MaterialCatalog.Entry("minecraft:water", true, false));
        entries.add(new MaterialCatalog.Entry("minecraft:iron_pickaxe", false, true));
        entries.add(new MaterialCatalog.Entry("minecraft:waxed_oxidized_copper_stairs", true, true));
        entries.add(new MaterialCatalog.Entry("minecraft:oxidized_copper_bulb", true, true));
        entries.add(new MaterialCatalog.Entry("minecraft:cut_copper_stairs", true, true));
        return entries;
    }

    private MaterialCatalog catalog() {
        return new MaterialCatalog("26.2-test", fixtures(), id ->
            new MaterialCatalog.StateDescription(id + "[waterlogged=false]", Map.of("waterlogged", List.of("true", "false")), List.of("waterloggable")));
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> results(Map<String, Object> page) {
        return (List<Map<String, Object>>) page.get("results");
    }

    @Test void summaryIsTinyAndContainsCountsRatherThanIds() {
        var summary = catalog().summary();
        assertEquals(75, summary.get("materials"));
        assertEquals(74L, summary.get("blocks"));
        assertEquals(74L, summary.get("items"));
        assertEquals(16, summary.get("search_default_limit"));
        assertEquals(32, summary.get("search_max_limit"));
        String json = new Gson().toJson(summary);
        assertTrue(json.length() < 200);
        assertFalse(json.contains("minecraft:"));
    }

    @Test void searchDefaultsToBlocksAndSixteenCompactResults() {
        var page = catalog().search(null, null, null, null);
        assertEquals("block", page.get("kind"));
        assertEquals(74, page.get("total"));
        assertEquals(16, results(page).size());
        assertTrue(results(page).stream().allMatch(entry -> entry.keySet().equals(Set.of("id", "block", "item"))));
        assertTrue(((String) page.get("next_cursor")).length() < 100);
    }

    @Test void allPagesAreStableBoundedAndDoNotDuplicateOrLoseEntries() {
        var catalog = catalog();
        String cursor = null;
        List<String> found = new ArrayList<>();
        int pages = 0;
        do {
            var page = catalog.search("", "all", 32, cursor);
            assertTrue(results(page).size() <= 32);
            for (var result : results(page)) found.add((String) result.get("id"));
            cursor = (String) page.get("next_cursor");
            pages++;
        } while (cursor != null);
        assertEquals(3, pages);
        assertEquals(75, found.size());
        assertEquals(75, new HashSet<>(found).size());
        assertEquals(found.stream().sorted().toList(), found);
    }

    @Test void tokenSearchRequiresEveryTokenAndIgnoresCase() {
        var page = catalog().search("  COPPER   stair  ", "block", 32, null);
        assertEquals("copper stair", page.get("query"));
        assertEquals(2, results(page).size());
        assertTrue(results(page).stream().allMatch(entry -> ((String) entry.get("id")).contains("copper_stairs")));
        assertEquals(0, catalog().search("copper unknown", "all", 32, null).get("total"));
    }

    @Test void itemKindIncludesInventoryBlocksButExcludesFluids() {
        var catalog = catalog();
        assertEquals(0, catalog.search("water", "item", 16, null).get("total"));
        assertEquals(1, catalog.search("water", "block", 16, null).get("total"));
        assertEquals(1, catalog.search("pickaxe", "item", 16, null).get("total"));
        assertEquals(0, catalog.search("pickaxe", "block", 16, null).get("total"));
    }

    @Test void rejectsCursorWhenCatalogOrSearchChanges() {
        var catalog = catalog();
        String cursor = (String) catalog.search("block", "all", 16, null).get("next_cursor");
        assertEquals("invalid_cursor", assertThrows(RpcServer.Fault.class,
            () -> catalog.search("water", "all", 16, cursor)).code);
        assertEquals("invalid_cursor", assertThrows(RpcServer.Fault.class,
            () -> catalog.search("block", "item", 16, cursor)).code);
        var changed = new MaterialCatalog("26.3-test", fixtures(), id -> null);
        assertEquals("stale_cursor", assertThrows(RpcServer.Fault.class,
            () -> changed.search("block", "all", 16, cursor)).code);
        var reordered = new ArrayList<>(fixtures());
        Collections.reverse(reordered);
        assertEquals(catalog.summary().get("version"), new MaterialCatalog("26.2-test", reordered, id -> null).summary().get("version"));
    }

    @Test void rejectsMalformedAndOversizedArguments() {
        var catalog = catalog();
        for (int limit : List.of(-1, 0, 33, Integer.MAX_VALUE))
            assertEquals("invalid_material_query", assertThrows(RpcServer.Fault.class, () -> catalog.search("", "all", limit, null)).code);
        assertThrows(RpcServer.Fault.class, () -> catalog.search("", "nonsense", null, null));
        assertThrows(RpcServer.Fault.class, () -> catalog.search("x".repeat(97), "all", null, null));
        assertEquals(0, catalog.search("x".repeat(96), "all", null, null).get("total"));
        assertThrows(RpcServer.Fault.class, () -> catalog.search("x\ny", "all", null, null));
        for (String cursor : List.of("bad", "x".repeat(101), "::", "0".repeat(24) + ":" + "0".repeat(24) + ":2147483647"))
            assertEquals("invalid_cursor", assertThrows(RpcServer.Fault.class, () -> catalog.search("", "all", null, cursor)).code);
        String valid = (String) catalog.search("", "all", 16, null).get("next_cursor");
        String beyond = valid.substring(0, valid.lastIndexOf(':') + 1) + "999999999";
        assertEquals("invalid_cursor", assertThrows(RpcServer.Fault.class, () -> catalog.search("", "all", 16, beyond)).code);
    }

    @Test void describeLoadsOnlyTheExactBlockRequested() {
        AtomicInteger calls = new AtomicInteger();
        var catalog = new MaterialCatalog("test", fixtures(), id -> {
            calls.incrementAndGet();
            return new MaterialCatalog.StateDescription(id, Map.of(), List.of());
        });
        catalog.summary();
        catalog.search("", "all", 16, null);
        assertEquals(0, calls.get());
        var description = catalog.describe("water");
        assertEquals("minecraft:water", description.get("default_state"));
        assertEquals(true, description.get("placeable"));
        assertEquals(1, calls.get());
        var item = catalog.describe("minecraft:iron_pickaxe");
        assertEquals(false, item.get("placeable"));
        assertEquals(true, item.get("item"));
        assertFalse(item.containsKey("default_state"));
        assertFalse(item.containsKey("properties"));
        assertEquals(1, calls.get());
    }

    @Test void rejectsUnknownLegacyAndNonExactIds() {
        for (String id : List.of("minecraft:missing", "minecraft:legacy_stone", "stone[axis=y]", "stone{}", "STONE", "mod:stone", "", "x".repeat(129)))
            assertEquals("invalid_material", assertThrows(RpcServer.Fault.class, () -> catalog().describe(id)).code);
        assertEquals("invalid_material", assertThrows(RpcServer.Fault.class, () -> catalog().describe(null)).code);
    }

    @Test void describesBooleanIntegerAndEnumDomainsWithoutAStateProduct() throws Exception {
        var state = new FakeState(List.of(
            new FakeProperty("waterlogged", List.of(false, true)),
            new FakeProperty("age", List.of(0, 1, 2, 3)),
            new FakeProperty("facing", List.of(Facing.N, Facing.S))));
        var properties = MaterialCatalog.readProperties(state);
        assertEquals(List.of("false", "true"), properties.get("waterlogged"));
        assertEquals(List.of("0", "1", "2", "3"), properties.get("age"));
        assertEquals(List.of("north", "south"), properties.get("facing"));
        assertEquals(List.of("age", "facing", "waterlogged"), new ArrayList<>(properties.keySet()));
        assertEquals(8, properties.values().stream().mapToInt(List::size).sum());
        assertEquals(0, MaterialCatalog.readProperties(new FakeState(List.of())).size());
    }

    @Test void enormousOrDuplicatePropertyDomainsFailRatherThanTruncate() {
        var enormous = new FakeState(List.of(new FakeProperty("age", IntStream.range(0, 257).boxed().toList())));
        assertEquals("material_properties_unavailable", assertThrows(RpcServer.Fault.class,
            () -> MaterialCatalog.readProperties(enormous)).code);
        var duplicate = new FakeState(List.of(new FakeProperty("age", List.of(0)), new FakeProperty("age", List.of(0))));
        assertThrows(RpcServer.Fault.class, () -> MaterialCatalog.readProperties(duplicate));
    }

    enum Facing { N, S }
    public record FakeState(Collection<FakeProperty> properties) {
        public Collection<FakeProperty> getProperties() { return properties; }
    }
    public record FakeProperty(String name, Collection<?> values) {
        public String getName() { return name; }
        public Collection<?> getPossibleValues() { return values; }
        public String getName(Comparable<?> value) {
            return value instanceof Facing facing ? (facing == Facing.N ? "north" : "south") : value.toString();
        }
    }
}
