package io.github.minecraftbuilder.core;

/** Bounded summary for an explicit administrator decision; matching content never proves authorship. */
public record RecoveryReview(String operationId, String planId, int positions, int matchesBefore,
                             int matchesAfter, int foreignStates, String currentDigest, long sampledAtMillis) { }
