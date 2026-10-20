import { useEffect, useState } from 'react'

export default function App() {
  const [result, setResult] = useState('loading…')

  useEffect(() => {
    fetch('http://localhost:8000/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json()
      })
      .then((data) => {
        setResult(data.status === 'ok' ? 'Backend: ok' : `Backend: ${data.status}`)
      })
      .catch((err) => setResult(`Backend: unreachable (${err.message})`))
  }, [])

  return (
    <main style={{ fontFamily: 'sans-serif', padding: '2rem' }}>
      <h1>Frager</h1>
      <p data-testid="backend-status">{result}</p>
    </main>
  )
}
