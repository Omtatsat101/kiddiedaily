import './globals.css'

export const metadata = {
  title: 'KiddieDaily — AI-Curated Kids Health & Wellness News',
  description: 'Like Ground News, but for raising healthy kids. Multi-source, zero-bias, trust-spectrum-scored news for parents. Vaccines, nutrition, development, safety — all balanced.',
  openGraph: {
    title: 'KiddieDaily — Ground News for Kids Health',
    description: 'AI-curated daily digest of kids health, wellness, and development news from 50+ sources.',
    url: 'https://kiddiedaily.com',
    type: 'website',
  },
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
