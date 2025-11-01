const PREFIX = "/tur";
const CACHE_TTL = 86400; // 1 天

function addSecurityHeaders(headers) {
  headers.set('Strict-Transport-Security', 'max-age=31536000; includeSubDomains; preload');
  headers.set('X-Frame-Options', 'DENY');
  headers.set('X-XSS-Protection', '1; mode=block');
  headers.set(
    'Content-Security-Policy',
    "default-src 'none'; " +
    "img-src 'self'; " +
    "script-src 'self' https://cdn.tailwindcss.com https://tur-mirror.pages.dev; " +
    "style-src 'self' https://cdn.tailwindcss.com https://tur-mirror.pages.dev;"
  );
  headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
  headers.set('Permissions-Policy', 'interest-cohort=()');
  return headers;
}

function isCN(request) {
  const country = request.headers.get('cf-ipcountry') || '';
  return country.toUpperCase() === 'CN';
}

function isFile(path) {
  return !path.endsWith('/');
}

async function streamFetch(url, request) {
  // 使用 streaming + HTTP/2/3 + Keep-Alive
  const fetchOptions = {
    method: request.method,
    headers: request.headers,
    redirect: 'follow',
    cf: {
      cacheEverything: false,
      http3: true,
      preconnect: true
    }
  };
  const resp = await fetch(url, fetchOptions);
  if (!resp.ok) throw new Error(`Fetch failed: ${resp.status}`);
  return new Response(resp.body, {
    status: resp.status,
    headers: resp.headers
  });
}

async function handleRequest(request, env, ctx) {
  const url = new URL(request.url);
  if (!url.pathname.startsWith(PREFIX)) {
    return Response.redirect("https://tur-mirror.pages.dev", 302);
  }

  const subPath = url.pathname.slice(PREFIX.length);
  const pathArray = subPath.split("/").filter(Boolean);

  /** @type {Cache} */
  // @ts-ignore
  const cache = caches.default;

  // /dists/*
  if (subPath.startsWith("/dists")) {
    const targetUrl = "https://cdn.jsdelivr.net/gh/termux-user-repository/dists@master/dists" + subPath.replace("/dists", "");
    return fetch(targetUrl, {
      method: request.method,
      headers: request.headers,
      redirect: 'follow',
      cf: { cacheEverything: true, cacheTtl: CACHE_TTL, http3: true, preconnect: true }
    });
  }

  // /pool/*
  if (subPath.startsWith("/pool")) {
    const lastSegment = pathArray.at(-1);
    const isFileRequest = isFile(url.pathname);

    if (!isFileRequest) {
      const mirroredUrl = "https://tur-mirror.pages.dev" + subPath + url.search;
      return fetch(mirroredUrl, request);
    }

    const cacheKey = new Request(url.toString(), request);
    const cachedResponse = await cache.match(cacheKey);
    if (cachedResponse) return cachedResponse;

    const packageDebNameModified = lastSegment.replaceAll(/[^a-zA-Z0-9-_+%]+/g, ".");
    const packageName = lastSegment.split("_")[0];
    const legacyUrl = "https://github.com/termux-user-repository/dists/releases/download/0.1/" + packageDebNameModified;
    const primaryUrl = "https://github.com/termux-user-repository/dists/releases/download/" + packageName + "/" + packageDebNameModified;

    let finalUrl;
    if (isCN(request)) {
      const xgetPrimary = primaryUrl.replace("https://github.com/", "https://xget.835927.xyz/gh/");
      const xgetLegacy = legacyUrl.replace("https://github.com/", "https://xget.835927.xyz/gh/");
      try {
        const head = await fetch(xgetPrimary, { method: "HEAD", redirect: "follow" });
        if (head.ok) finalUrl = xgetPrimary;
      } catch (e) {}
      if (!finalUrl) finalUrl = xgetLegacy;
    } else {
      try {
        const head = await fetch(primaryUrl, { method: "HEAD", redirect: "follow" });
        if (head.ok) finalUrl = primaryUrl;
      } catch (e) {}
      if (!finalUrl) {
        try {
          const headLegacy = await fetch(legacyUrl, { method: "HEAD", redirect: "follow" });
          if (headLegacy.ok) finalUrl = legacyUrl;
        } catch (e) {}
      }
      if (!finalUrl) finalUrl = "https://tur-mirror.pages.dev" + subPath + url.search;
    }

    // 🚀 使用 streaming fetch，不再跳转，直接代理下载
    const response = await streamFetch(finalUrl, request);
    const headers = new Headers(response.headers);
    headers.set("Cache-Control", `public, max-age=${CACHE_TTL}`);
    const streamResponse = new Response(response.body, { status: response.status, headers });

    ctx.waitUntil(cache.put(cacheKey, streamResponse.clone()));
    return streamResponse;
  }

  // /tur/* 其他 → tur-mirror
  const mirroredUrl = "https://tur-mirror.pages.dev" + subPath + url.search;
  return fetch(mirroredUrl, {
    method: request.method,
    headers: request.headers,
    redirect: 'follow',
    cf: { cacheEverything: true, cacheTtl: CACHE_TTL, http3: true, preconnect: true }
  });
}

export default {
  async fetch(request, env, ctx) {
    try {
      return await handleRequest(request, env, ctx);
    } catch (err) {
      return new Response(err.stack || String(err), {
        status: 500,
        headers: addSecurityHeaders(new Headers())
      });
    }
  }
};
