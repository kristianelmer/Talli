import type { MetadataRoute } from "next";

const publicRoutes = [
  "",
  "/sjekk-selskapet",
  "/passer-talli",
  "/pris",
  "/hjelp",
  "/vilkar",
  "/personvern",
  "/databehandleravtale",
  "/sikkerhet",
  "/status",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return publicRoutes.map((route, index) => ({
    url: `https://talli.no${route}`,
    changeFrequency: index <= 4 ? "weekly" : "monthly",
    priority: index === 0 ? 1 : index <= 4 ? 0.8 : 0.5,
  }));
}
