import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,
  images: {
    unoptimized: process.env.NODE_ENV !== 'development' ? true : false,
  },
};

export default nextConfig;
