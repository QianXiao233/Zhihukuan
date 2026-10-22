import JSEncrypt from 'jsencrypt'

async function encryptPassword(password) {
  const response = await fetch('/api/get_rsa')
  if (!response.ok) throw new Error(`公钥请求失败（${response.status}）`)
  const publicKey = await response.text()
  const encrypt = new JSEncrypt()
  encrypt.setPublicKey(publicKey)
  const encrypted = encrypt.encrypt(password)
  if (!encrypted) throw new Error('密码加密失败')
  return encrypted
}

export async function login(form) {
  const encryptedPassword = await encryptPassword(form.password)
  const params = new URLSearchParams({ username: form.username, enpassword: encryptedPassword })
  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  })
  const result = await response.json().catch(() => ({}))
  if (!response.ok) return { success: false, message: result.message || `请求失败（${response.status}）` }
  return result
}

export async function validateToken(token) {
  const params = new URLSearchParams({ token })
  const response = await fetch('/auth/validate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params.toString(),
  })
  return response.ok ? response.json() : { success: false }
}

export function clearAuth() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  localStorage.removeItem('level')
  window.dispatchEvent(new Event('platform-logout'))
}
