package io.github.minecraftbuilder.core;

import java.io.IOException;
import java.util.List;

/** save must return only after durable persistence; failures must throw, never be swallowed. */
public interface Journal {
    void savePlan(Plan plan) throws IOException;
    void saveOperation(OperationSnapshot operation) throws IOException;
    List<Plan> loadPlans() throws IOException;
    List<OperationSnapshot> loadOperations() throws IOException;
}
