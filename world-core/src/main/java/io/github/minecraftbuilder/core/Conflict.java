package io.github.minecraftbuilder.core;

public record Conflict(BlockPos pos, String expected, String current, String desired, String reason) { }
