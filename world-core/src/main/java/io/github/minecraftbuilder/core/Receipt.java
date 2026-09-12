package io.github.minecraftbuilder.core;

/** Only records a block actually written and observed at its desired state. */
public record Receipt(Change change, long revision) { }
