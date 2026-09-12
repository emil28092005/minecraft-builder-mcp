package io.github.minecraftbuilder.core;

public record BlockPos(int x, int y, int z) implements Comparable<BlockPos> {
    public BlockPos add(BlockPos offset) {
        return new BlockPos(Math.addExact(x, offset.x), Math.addExact(y, offset.y), Math.addExact(z, offset.z));
    }

    @Override public int compareTo(BlockPos other) {
        int cmp = Integer.compare(y, other.y);
        if (cmp == 0) cmp = Integer.compare(z, other.z);
        if (cmp == 0) cmp = Integer.compare(x, other.x);
        return cmp;
    }
}
