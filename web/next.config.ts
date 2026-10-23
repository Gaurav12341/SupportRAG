import type { NextConfig } from "next";

// The browser only ever talks to this Next.js server. It calls the FastAPI backend (BACKEND_URL) itself, with the login token
// kept in an httpOnly cookie, so the token never reaches page scripts. See app/api/.
const config: NextConfig = {
  poweredByHeader: false,
  allowedDevOrigins: ["127.0.0.1"], // `next dev` serves its scripts only to origins it knows; the README opens the app at 127.0.0.1
};

export default config;
