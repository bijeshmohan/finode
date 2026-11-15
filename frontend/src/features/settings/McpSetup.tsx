// How to set up an assistant with a token (partials/mcp_setup.html): the server address and the snippets for Claude
// Code, Claude Desktop and the rest, filled with the new token's secret or the placeholder YOUR_TOKEN.
import styles from "./Settings.module.css";

export function McpSetup({ url, secret }: { url: string; secret: string | null }) {
  const token = secret ?? "YOUR_TOKEN";
  return (
    <>
      <p className={styles.muted}>
        Server address: <code>{url}</code>, with the header{" "}
        <code>Authorization: Bearer {secret ? "…" : "<token>"}</code>.
        {!secret && (
          <>
            {" "}
            Replace <code>YOUR_TOKEN</code> below with a token you created.
          </>
        )}
      </p>
      <h3 className={styles.subhead}>Claude Code</h3>
      <pre className={styles.snippet}>
        {`claude mcp add --transport http finode ${url} --header "Authorization: Bearer ${token}"`}
      </pre>
      <h3 className={styles.subhead}>Claude Desktop</h3>
      <p className={styles.muted}>
        Settings › Developer › Edit config, add this to <code>claude_desktop_config.json</code> and restart Claude.
        Needs Node.js.
      </p>
      <pre className={styles.snippet}>
        {`{
  "mcpServers": {
    "finode": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "${url}", "--header", "Authorization:\${FINODE_AUTH}"],
      "env": { "FINODE_AUTH": "Bearer ${token}" }
    }
  }
}`}
      </pre>
      <h3 className={styles.subhead}>Cursor, VS Code and others</h3>
      <p className={styles.muted}>Any client that takes a URL and headers for a remote (HTTP) MCP server.</p>
      <pre className={styles.snippet}>
        {`{
  "mcpServers": {
    "finode": {
      "url": "${url}",
      "headers": { "Authorization": "Bearer ${token}" }
    }
  }
}`}
      </pre>
    </>
  );
}
