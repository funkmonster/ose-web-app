// Thin API client. Passphrase is stored in localStorage after first login.

const KEY = 'ose_passphrase'

export const getPassphrase = () => localStorage.getItem(KEY) || ''
export const setPassphrase = (p) => localStorage.setItem(KEY, p)
export const clearPassphrase = () => localStorage.removeItem(KEY)

async function request(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Passphrase': getPassphrase(),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

async function requestFile(path, file) {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'X-Passphrase': getPassphrase() },
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  return res.json()
}

export const api = {
  login: (passphrase) => request('POST', '/api/login', { passphrase }),
  me: () => request('GET', '/api/me'),
  campaign: () => request('GET', '/api/campaign'),
  startCampaign: (name, module) => request('POST', '/api/campaign/start', { name, module }),
  feed: () => request('GET', '/api/feed'),
  recap: () => request('GET', '/api/recap'),
  summary: () => request('GET', '/api/summary'),
  play: (action) => request('POST', '/api/play', { action }),
  roll: (notation, reason, reportedResult) =>
    request('POST', '/api/roll', { notation, reason, reported_result: reportedResult ?? null }),
  character: () => request('GET', '/api/character'),
  createCharacter: (data) => request('POST', '/api/character', data),
  importSheet: (file) => requestFile('/api/character/import_sheet', file),
  party: () => request('GET', '/api/party'),
  updateInventory: (inventory) => request('PUT', '/api/character/inventory', { inventory }),
  updateWeaponsArmor: (weapons_armor) =>
    request('PUT', '/api/character/weapons_armor', { weapons_armor }),
  updateSpells: (spells) => request('PUT', '/api/character/spells', { spells }),
  rest: (rest_type) => request('POST', '/api/rest', { rest_type }),
  gmSay: (message) => request('POST', '/api/gm/say', { message }),
  gmUpdateHP: (target_user, delta) => request('POST', '/api/gm/update_hp', { target_user, delta }),
  setPhysicalDiceMode: (enabled) => request('POST', '/api/gm/physical_dice_mode', { enabled }),
  resetCampaign: () => request('POST', '/api/gm/reset_campaign'),
}
