/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'cdn.discordapp.com',
      },
    ],
  },
  webpack: (config) => {
    // Disable persistent caching in Next.js build to prevent out-of-memory errors on 512MB RAM hosts (Render free tier)
    config.cache = false;
    return config;
  },
};

module.exports = nextConfig;