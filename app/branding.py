from fastapi import APIRouter, Response
from fastapi.responses import RedirectResponse

router = APIRouter()

LOGO_SVG = '''<svg width="64" height="64" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="RevenueLens">
  <defs>
    <linearGradient id="rlLogoGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#4f46e5"/>
      <stop offset="100%" stop-color="#7c3aed"/>
    </linearGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="14" fill="url(#rlLogoGrad)"/>
  <circle cx="28" cy="28" r="18" stroke="white" stroke-width="5" fill="none" stroke-linecap="round"/>
  <line x1="42" y1="42" x2="54" y2="54" stroke="white" stroke-width="5" stroke-linecap="round"/>
  <polyline points="18,36 26,28 34,34 42,26" stroke="white" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>'''

_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}

@router.get("/favicon.svg")
async def favicon_svg():
    return Response(LOGO_SVG, media_type="image/svg+xml", headers=_CACHE_HEADERS)

@router.get("/logo.svg")
async def logo_svg():
    return Response(LOGO_SVG, media_type="image/svg+xml", headers=_CACHE_HEADERS)

@router.get("/favicon.ico")
async def favicon_ico():
    return RedirectResponse("/favicon.svg", status_code=307)
