import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  agents,
  buildSystemPrompt,
  findAgent,
  findCase,
  getPublicAgents,
  getPublicCases
} from "./agents.js";
import { createSalesReply, getDeepSeekConfig } from "./deepseek.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const publicDir = path.join(rootDir, "public");

const app = express();
const port = Number(process.env.PORT || 4173);

app.use(express.json({ limit: "1mb" }));
app.use(express.static(publicDir));

app.get("/api/health", (_request, response) => {
  const config = getDeepSeekConfig();
  response.json({
    ok: true,
    model: config.model,
    hasApiKey: Boolean(config.apiKey),
    agents: agents.length
  });
});

app.get("/api/agents", (_request, response) => {
  response.json({
    salesCases: getPublicCases(),
    agents: getPublicAgents()
  });
});

app.post("/api/chat", async (request, response) => {
  try {
    const { agentId, caseId, messages } = request.body || {};
    const agent = findAgent(agentId);
    const salesCase = findCase(caseId);

    if (!agent) {
      response.status(404).json({ error: "Unknown agent selected." });
      return;
    }

    if (!Array.isArray(messages)) {
      response.status(400).json({ error: "messages must be an array." });
      return;
    }

    const result = await createSalesReply({
      systemPrompt: buildSystemPrompt(agent, salesCase),
      messages,
      salesCase
    });

    response.json({
      agentId,
      caseId: salesCase.id,
      content: result.content,
      usage: result.usage,
      toolLog: result.toolLog
    });
  } catch (error) {
    response.status(500).json({
      error: error instanceof Error ? error.message : "Unexpected server error."
    });
  }
});

app.get("*", (_request, response) => {
  response.sendFile(path.join(publicDir, "index.html"));
});

app.listen(port, () => {
  console.log(`DeepSeek sales panel running at http://localhost:${port}`);
});
