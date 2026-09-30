#!/usr/bin/env node
import { realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { loadContent, type Content } from './content.js';
import { registerResources } from './resources.js';
import { registerPrompts } from './prompts.js';
import { registerSearchMethodology } from './tools/search_methodology.js';
import { registerGetDocument } from './tools/get_document.js';
import { registerListPresets } from './tools/list_presets.js';
import { registerListQeBlueprints } from './tools/list_qe_blueprints.js';
import { registerListSdlcPhases } from './tools/list_sdlc_phases.js';
import { registerPlanInstall } from './tools/plan_install.js';
import { registerRunDoctor } from './tools/run_doctor.js';

export function createServer(content: Content): McpServer {
  const server = new McpServer(
    { name: 'agentic-os', version: '0.3.2' },
    {
      capabilities: { resources: {}, prompts: {}, tools: {} },
      instructions:
        'Serves the agentic-os governance, agentic-sdlc pipeline, and agentic-qe ' +
        'blueprint methodology. Read-only: it returns documents and plans, and ' +
        'never writes to the repository. Start with search_methodology.',
    },
  );
  registerResources(server, content);
  registerPrompts(server, content);
  registerSearchMethodology(server, content);
  registerGetDocument(server, content);
  registerListPresets(server, content);
  registerListQeBlueprints(server, content);
  registerListSdlcPhases(server, content);
  registerPlanInstall(server, content);
  registerRunDoctor(server);
  return server;
}

async function main(): Promise<void> {
  const server = createServer(await loadContent());
  await server.connect(new StdioServerTransport());
}

// Run main() only when this file is the process entrypoint. `process.argv[1]`
// is the path node was asked to run — but when the server is launched through
// npm's `node_modules/.bin/agentic-os-mcp` (a link, which is what `npx`, a
// global install, and every MCP client config actually do), argv[1] is the
// link's own path while `import.meta.url` is the fully resolved real path of
// dist/index.js, so a raw `file://${argv[1]}` comparison never matches and the
// server exits 0 without ever connecting. Canonicalizing argv[1] through
// realpathSync() — and building the URL with pathToFileURL() so paths with
// spaces/special chars encode correctly — makes both sides the same file URL.
// The `argv[1] &&` guard keeps `createServer` importable from tests, where
// argv[1] is the test runner, not this module.
const invokedPath = process.argv[1];
if (invokedPath && import.meta.url === pathToFileURL(realpathSync(invokedPath)).href) {
  main().catch((err: unknown) => {
    console.error(
      'agentic-os-mcp failed to start:',
      err instanceof Error ? err.message : String(err),
    );
    process.exit(1);
  });
}
