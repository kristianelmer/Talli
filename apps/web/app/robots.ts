import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: [
        "/",
        "/sjekk-selskapet",
        "/passer-talli",
        "/pris",
        "/hjelp",
        "/vilkar",
        "/personvern",
        "/databehandleravtale",
        "/sikkerhet",
        "/status",
      ],
      disallow: [
        "/api/",
        "/operator/",
        "/dashboard/",
        "/workspace/",
        "/onboarding/",
        "/transactions/",
        "/filing/",
        "/archive/",
      ],
    },
    sitemap: "https://talli.no/sitemap.xml",
    host: "https://talli.no",
  };
}
