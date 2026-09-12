package io.github.minecraftbuilder.core;

public enum OperationStatus {
    QUEUED, APPLYING, APPLIED, CONFLICT, CANCELLED, FAILED, RECOVERY_REQUIRED;
    public boolean terminal() { return this != QUEUED && this != APPLYING; }
}
