package dev.minecraftbuilder.camera;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class AutoConnectPolicyTest {
    @Test void onlyExplicitUnprivilegedLoopbackTargetsAreAccepted() {
        assertEquals("127.0.0.1:25575", new AutoConnectPolicy("127.0.0.1:25575",0).target());
        for(String target:new String[]{"example.com:25565","localhost:25575","127.0.0.1:80","127.0.0.1:99999","127.0.0.1:25575/","127.0.0.1:25575\n"})
            assertThrows(IllegalArgumentException.class,()->new AutoConnectPolicy(target,0));
    }
    @Test void retriesAreThrottledAndNeverInterruptAConnectionOrOtherScreen() {
        var policy=new AutoConnectPolicy("127.0.0.1:25575",0);
        assertFalse(policy.due(9999,false,true,false));
        assertTrue(policy.due(10000,false,true,false));
        assertFalse(policy.due(10001,false,true,false));
        assertFalse(policy.due(20000,false,false,false));
        assertFalse(policy.due(20000,false,true,true));
        assertTrue(policy.due(20000,false,true,false));
        assertFalse(policy.due(40000,true,true,false));
        assertFalse(policy.due(40001,false,true,false));
        assertTrue(policy.due(50000,false,true,false));
        assertEquals(3,policy.attempts());
    }
}
