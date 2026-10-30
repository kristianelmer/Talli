import {getCurrentSessionAccessToken} from "../../../lib/supabase/auth-session";
import {loadAccountsDeliveryOriginal} from "../../../../features/annual-accounts-filing";
import {TalliApiError} from "@talli/talli-api-client";

export const dynamic="force-dynamic";

export async function GET(request: Request) {
  const token=await getCurrentSessionAccessToken();
  if (!token) return new Response("Innlogging kreves.",{status:401,headers:{"Cache-Control":"no-store"}});
  const query=new URL(request.url).searchParams;
  try {
    const value=await loadAccountsDeliveryOriginal(token,query.get("companyId") ?? "",Number(query.get("incomeYear")),query.get("filingId") ?? "",query.get("key") ?? "");
    const bytes=Buffer.from(value.bodyBase64,"base64");
    const extension=value.mediaType.split(";",1)[0]==="application/json"?"json":value.mediaType.split(";",1)[0]==="application/xml"?"xml":value.mediaType==="application/pdf"?"pdf":"bin";
    const filename=`aarsregnskap-${value.incomeYear}-${value.filingId}-${value.purpose.replace(/[^a-z_]/gu,"")}.${extension}`;
    return new Response(bytes,{headers:{"Content-Type":"application/octet-stream","Content-Disposition":`attachment; filename="${filename}"`,
      "Content-Length":String(bytes.length),"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff","X-Original-SHA256":value.sha256}});
  } catch (error) {
    const status=error instanceof TalliApiError && [401,403,404].includes(error.status)?error.status:503;
    return new Response(status===403?"Ekstra identitetsbekreftelse kreves.":"Originalen kunne ikke hentes.",{status,headers:{"Cache-Control":"no-store"}});
  }
}
