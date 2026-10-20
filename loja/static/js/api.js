// Cliente da API local. Toda escrita envia o cabeçalho anti-CSRF.
export class ApiError extends Error {
  constructor(message, status, data) { super(message); this.status = status; this.data = data || {}; this.code = (data || {}).code; }
}

let onUnauthenticated = () => {};
export function setUnauthenticatedHandler(fn) { onUnauthenticated = fn; }

async function call(method, url, body, isForm) {
  const opts = { method, headers: { 'X-Requested-With': 'loja' }, credentials: 'same-origin' };
  if (body !== undefined) {
    if (isForm) opts.body = body;
    else { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  }
  let res;
  try { res = await fetch(url, opts); }
  catch (e) { throw new ApiError('Sem conexão com o servidor do sistema. Verifique se a janela do sistema continua aberta.', 0); }
  const type = res.headers.get('content-type') || '';
  if (type.includes('application/json')) {
    const data = await res.json();
    if (!res.ok) {
      if (res.status === 401 && data.code === 'unauthenticated') onUnauthenticated();
      throw new ApiError(data.error || 'Erro inesperado.', res.status, data);
    }
    return data;
  }
  if (!res.ok) throw new ApiError('Erro ' + res.status, res.status);
  return res;
}

export const api = {
  get: (url) => call('GET', url),
  post: (url, body) => call('POST', url, body === undefined ? {} : body),
  put: (url, body) => call('PUT', url, body),
  del: (url) => call('DELETE', url),
  upload: (url, formData) => call('POST', url, formData, true),
};

export function qs(obj) {
  const p = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== '') p.set(k, v); });
  const s = p.toString();
  return s ? '?' + s : '';
}
