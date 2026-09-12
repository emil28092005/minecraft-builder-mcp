package io.github.minecraftbuilder.core;

@FunctionalInterface
public interface BlockPolicy {
    boolean supports(String canonicalState);
}
