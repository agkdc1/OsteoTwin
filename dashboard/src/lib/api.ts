/** OsteoTwin API client */

const SIM_URL = '/sim-api';

export function getToken(): string | null {
  return localStorage.getItem('osteotwin_token');
}

export function setToken(token: string, username: string) {
  localStorage.setItem('osteotwin_token', token);
  localStorage.setItem('osteotwin_user', username);
}

export function clearToken() {
  localStorage.removeItem('osteotwin_token');
  localStorage.removeItem('osteotwin_user');
}

export function getUsername(): string {
  return localStorage.getItem('osteotwin_user') || '';
}

async function authFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401) {
    clearToken();
    window.location.href = '/';
  }
  return resp;
}

function simKey(): string {
  return localStorage.getItem('osteotwin_sim_key') || '';
}

async function simFetch(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-API-Key': simKey(),
    ...(options.headers as Record<string, string> || {}),
  };
  return fetch(SIM_URL + path, { ...options, headers });
}

// --- Auth ---
export async function login(username: string, password: string) {
  const resp = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) throw new Error((await resp.json()).detail || 'Login failed');
  const data = await resp.json();
  setToken(data.access_token, username);
  return data;
}

// --- Health ---
export async function planHealth() {
  const resp = await fetch('/health');
  return resp.ok ? await resp.json() : null;
}

export async function simHealth() {
  try {
    const resp = await fetch('http://localhost:8300/health');
    return resp.ok ? await resp.json() : null;
  } catch { return null; }
}

export async function kgStatus() {
  const resp = await fetch('/api/v1/knowledge/status');
  return resp.ok ? await resp.json() : { connected: false };
}

// --- Pipeline ---
export async function surgicalQuery(query: string, caseId: string, aoCode?: string) {
  const resp = await authFetch('/api/v1/pipeline/query', {
    method: 'POST',
    body: JSON.stringify({ query, case_id: caseId, ao_code: aoCode }),
  });
  return resp.json();
}

export async function startDebate(caseSummary: string, caseId: string, aoCode?: string, maxRounds = 3) {
  const resp = await authFetch('/api/v1/pipeline/debate', {
    method: 'POST',
    body: JSON.stringify({ case_summary: caseSummary, case_id: caseId, ao_code: aoCode, max_rounds: maxRounds }),
  });
  return resp.json();
}

// --- Simulation ---
export async function listMeshes(branch = 'main') {
  const resp = await simFetch(`/v1/meshes?branch=${branch}`);
  return resp.json();
}

export async function listBranches() {
  const resp = await simFetch('/v1/branches');
  return resp.json();
}

export async function implantCatalog(type?: string) {
  const q = type ? `?implant_type=${type}` : '';
  const resp = await simFetch(`/v1/implants/catalog${q}`);
  return resp.json();
}

export async function suggestImplants(region: string, fragments: number, width: number) {
  const resp = await simFetch(`/v1/implants/suggest?bone_region=${region}&fragment_count=${fragments}&max_bone_width_mm=${width}`);
  return resp.json();
}

export async function listExports(caseId: string) {
  const resp = await simFetch(`/v1/export/stl/${caseId}`);
  return resp.json();
}
