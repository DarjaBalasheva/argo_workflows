// Положить тест в src/test/java/
import org.junit.jupiter.api.Test;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;

import static org.junit.jupiter.api.Assertions.*;

public class ArgoHelloWorkflowTest {

    private static final String NS = System.getenv().getOrDefault("ARGO_NAMESPACE", "argo");
    private static final String WF_FILE = System.getenv().getOrDefault("WORKFLOW_YAML", "hello-workflow.yaml");

    @Test
    void workflowSucceedsAndPrintsHelloWorld() throws Exception {
        System.out.printf("NS=%s WF_FILE=%s%n", NS, WF_FILE);

        // sanity: binaries exist
        run(List.of("argo", "version"), Duration.ofSeconds(30), true);
        run(List.of("kubectl", "version", "--client=true"), Duration.ofSeconds(30), true);

        // submit workflow, get name
        String wfName = run(List.of("argo", "submit", "-n", NS, "--output", "name", WF_FILE),
                Duration.ofSeconds(60), true).trim();
        assertFalse(wfName.isEmpty(), "Workflow name is empty");
        System.out.println("Submitted: " + wfName);

        try {
            // wait for completion (poll phase via kubectl jsonpath)
            String phase = waitWorkflowPhase(wfName, Duration.ofSeconds(90));
            assertEquals("Succeeded", phase, "Workflow did not succeed. Phase=" + phase);

            // logs must contain expected output
            String logs = run(List.of("argo", "logs", "-n", NS, wfName),
                    Duration.ofSeconds(60), true);
            assertTrue(logs.contains("hello world"),
                    "Expected 'hello world' in logs, got:\n" + logs);

        } finally {
            // cleanup (don't fail test if delete fails)
            run(List.of("argo", "delete", "-n", NS, wfName, "--yes"),
                    Duration.ofSeconds(30), false);
        }
    }

    private static String waitWorkflowPhase(String wfName, Duration maxWait) throws Exception {
        long deadline = System.currentTimeMillis() + maxWait.toMillis();
        String last = "";
        while (System.currentTimeMillis() < deadline) {
            String phase = run(
                    List.of("kubectl", "get", "wf", "-n", NS, wfName, "-o", "jsonpath={.status.phase}"),
                    Duration.ofSeconds(30),
                    true
            ).trim();

"src/test/java/ArgoHelloWorkflowTest.java" 103L, 3950B