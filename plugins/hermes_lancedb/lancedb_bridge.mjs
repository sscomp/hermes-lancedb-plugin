import { randomUUID } from "node:crypto";

const modulePath = process.env.HERMES_LANCEDB_LANCEDB_MODULE;
if (!modulePath) {
  throw new Error("HERMES_LANCEDB_LANCEDB_MODULE is required");
}

const lancedb = await import(modulePath);

const DB_PATH = process.env.HERMES_LANCEDB_DB_PATH;
const TABLE_NAME = process.env.HERMES_LANCEDB_TABLE_NAME || "memories";
const EMBEDDING_BASE_URL = process.env.HERMES_LANCEDB_EMBEDDING_BASE_URL || "http://127.0.0.1:11434/v1";
const EMBEDDING_MODEL = process.env.HERMES_LANCEDB_EMBEDDING_MODEL || "mxbai-embed-large:latest";
const EMBEDDING_API_KEY = process.env.HERMES_LANCEDB_EMBEDDING_API_KEY || "ollama-local";
const DECAY_HALF_LIFE_DAYS = Number(process.env.HERMES_LANCEDB_DECAY_HALF_LIFE_DAYS || 180);

if (!DB_PATH) {
  throw new Error("HERMES_LANCEDB_DB_PATH is required");
}

function escapeSqlLiteral(value) {
  return String(value).replace(/'/g, "''");
}

function scopeWhere(scopes) {
  if (!Array.isArray(scopes) || scopes.length === 0) return "";
  const parts = scopes.map((scope) => `scope = '${escapeSqlLiteral(scope)}'`);
  return `((${parts.join(" OR ")}) OR scope IS NULL)`;
}

function parseArgs() {
  const [cmd, raw] = process.argv.slice(2);
  return { cmd, args: raw ? JSON.parse(raw) : {} };
}

async function table() {
  const db = await lancedb.connect(DB_PATH);
  return db.openTable(TABLE_NAME);
}

function publicRecord(row, score = undefined) {
  const record = {
    id: row.id,
    text: row.text || "",
    category: row.category || "other",
    scope: row.scope || "global",
    importance: Number(row.importance || 0),
    timestamp: Number(row.timestamp || 0),
    metadata: typeof row.metadata === "string" ? row.metadata : JSON.stringify(row.metadata || {}),
  };
  if (score !== undefined) record._score = Number(score);
  return record;
}

function parseMetadata(value) {
  if (!value) return {};
  if (typeof value === "object") return value;
  try {
    const parsed = JSON.parse(String(value));
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function memoryAgeDays(row, now = Date.now()) {
  const started = Number(row.timestamp || parseMetadata(row.metadata).valid_from || now);
  return Math.max(0, (now - started) / 86400000);
}

function decayFactor(row) {
  if (!Number.isFinite(DECAY_HALF_LIFE_DAYS) || DECAY_HALF_LIFE_DAYS <= 0) return 1;
  const age = memoryAgeDays(row);
  return Math.pow(0.5, age / DECAY_HALF_LIFE_DAYS);
}

function accessBoost(row) {
  const metadata = parseMetadata(row.metadata);
  return Math.log1p(Number(metadata.access_count || 0)) * 0.25;
}

function governedScore(rawScore, row) {
  const importance = Number(row.importance || 0);
  return Number(rawScore || 0) * decayFactor(row) + importance * 0.5 + accessBoost(row);
}

async function touchRecords(t, records) {
  const now = Date.now();
  const touched = new Set();
  for (const record of records) {
    if (!record?.id || touched.has(record.id)) continue;
    touched.add(record.id);
    const metadata = parseMetadata(record.metadata);
    metadata.last_accessed_at = now;
    metadata.access_count = Number(metadata.access_count || 0) + 1;
    try {
      await t.update({
        where: `id = '${escapeSqlLiteral(record.id)}'`,
        values: { metadata: JSON.stringify(metadata) },
      });
    } catch {
      // Non-fatal.
    }
  }
}

function tokens(text) {
  return String(text || "")
    .toLowerCase()
    .split(/[\s,.;:!?()[\]{}<>/\\|"'`~@#$%^&*_+=-]+/)
    .filter(Boolean);
}

function lexicalScore(query, row) {
  const q = String(query || "").toLowerCase().trim();
  if (!q) return 0;
  const hay = `${row.text || ""} ${row.metadata || ""}`.toLowerCase();
  let score = hay.includes(q) ? 6 : 0;
  const qTokens = new Set(tokens(q));
  const hTokens = new Set(tokens(hay));
  for (const token of qTokens) {
    if (hTokens.has(token)) score += 2;
  }
  return governedScore(score, row);
}

async function embed(text) {
  const res = await fetch(`${EMBEDDING_BASE_URL.replace(/\/$/, "")}/embeddings`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${EMBEDDING_API_KEY}`,
    },
    body: JSON.stringify({ model: EMBEDDING_MODEL, input: text }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`embedding failed: ${res.status} ${body.slice(0, 240)}`);
  }
  const json = await res.json();
  const vector = json?.data?.[0]?.embedding;
  if (!Array.isArray(vector) || vector.length === 0) {
    throw new Error("embedding response did not include a vector");
  }
  return vector;
}

async function stats(args) {
  const t = await table();
  let query = t.query();
  const where = scopeWhere(args.scopes);
  if (where) query = query.where(where);
  const rows = await query.select(["scope", "category"]).toArray();
  const scopeCounts = {};
  const categoryCounts = {};
  for (const row of rows) {
    const scope = row.scope || "global";
    const category = row.category || "other";
    scopeCounts[scope] = (scopeCounts[scope] || 0) + 1;
    categoryCounts[category] = (categoryCounts[category] || 0) + 1;
  }
  return { totalCount: rows.length, scopeCounts, categoryCounts };
}

async function list(args) {
  const t = await table();
  let query = t.query();
  const where = scopeWhere(args.scopes);
  if (where) query = query.where(where);
  const rows = await query
    .select(["id", "text", "category", "scope", "importance", "timestamp", "metadata"])
    .toArray();
  return rows
    .map((row) => publicRecord(row))
    .sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0))
    .slice(Number(args.offset || 0), Number(args.offset || 0) + Math.min(Number(args.limit || 20), 100));
}

async function search(args) {
  const t = await table();
  const limit = Math.min(Math.max(Number(args.limit || 8), 1), 50);
  const fetchLimit = Math.min(limit * 10, 300);
  const where = scopeWhere(args.scopes);
  const merged = new Map();

  try {
    const vector = await embed(String(args.query || ""));
    let vectorQuery = t.vectorSearch(vector).distanceType("cosine").limit(fetchLimit);
    if (where) vectorQuery = vectorQuery.where(where);
    const rows = await vectorQuery.toArray();
    for (const row of rows) {
      const distance = Number(row._distance ?? 0);
      const score = governedScore(1 / (1 + distance), row);
      const record = publicRecord(row, score * 10);
      record._sources = ["vector"];
      merged.set(record.id, record);
    }
  } catch {
    // Fall through to FTS/lexical.
  }

  try {
    let query = t.search(String(args.query || ""), "fts").limit(fetchLimit);
    if (where) query = query.where(where);
    const rows = await query.toArray();
    for (const row of rows) {
      const ftsScore = row._score != null ? governedScore(Number(row._score), row) : lexicalScore(args.query, row);
      const existing = merged.get(row.id);
      if (existing) {
        existing._score = Number(existing._score || 0) + ftsScore;
        existing._sources.push("fts");
      } else {
        const record = publicRecord(row, ftsScore);
        record._sources = ["fts"];
        merged.set(record.id, record);
      }
    }
    if (merged.size > 0) {
      const result = [...merged.values()]
        .sort((a, b) => Number(b._score || 0) - Number(a._score || 0))
        .slice(0, limit);
      await touchRecords(t, result);
      return result;
    }
  } catch {
    // Fall through to lexical search.
  }

  let query = t.query();
  if (where) query = query.where(where);
  const rows = await query
    .select(["id", "text", "category", "scope", "importance", "timestamp", "metadata"])
    .toArray();
  const result = rows
    .map((row) => publicRecord(row, lexicalScore(args.query, row)))
    .filter((row) => Number(row._score || 0) > 0)
    .sort((a, b) => Number(b._score || 0) - Number(a._score || 0) || Number(b.timestamp || 0) - Number(a.timestamp || 0))
    .slice(0, limit);
  await touchRecords(t, result);
  return result;
}

async function add(args) {
  const content = String(args.content || "").trim();
  if (!content) throw new Error("content is required");
  const vector = await embed(content);
  const now = Date.now();
  const metadata = {
    l0_abstract: content.slice(0, 240),
    l1_overview: content,
    l2_content: content,
    memory_category: args.category || "fact",
    tier: "hermes-direct",
    source_session: args.sessionId || "",
    source: args.source || "hermes",
    valid_from: now,
    last_accessed_at: now,
    access_count: 0,
    confidence: Number(args.importance || 0.7),
  };
  const record = {
    id: randomUUID(),
    text: content,
    vector,
    category: args.category || "fact",
    scope: args.scope || "global",
    importance: Number(args.importance || 0.7),
    timestamp: now,
    metadata: JSON.stringify(metadata),
  };
  const t = await table();
  await t.add([record]);
  return publicRecord(record);
}

async function main() {
  const { cmd, args } = parseArgs();
  const handlers = { stats, list, search, add };
  const handler = handlers[cmd];
  if (!handler) {
    process.stdout.write(JSON.stringify({ ok: false, error: `unknown command: ${cmd}` }));
    process.exit(2);
  }
  try {
    const result = await handler(args);
    process.stdout.write(JSON.stringify({ ok: true, result }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ ok: false, error: String(error?.message || error) }));
    process.exit(1);
  }
}

await main();
