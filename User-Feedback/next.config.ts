import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
  devIndicators: false,
  images: {
    unoptimized: process.env.NODE_ENV !== 'development' ? true : false,
  },
};

export default nextConfig;
