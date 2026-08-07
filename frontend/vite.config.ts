import { defineConfig } from 'vite';

const BACKEND = process.env.BACKEND_ORIGIN ?? 'http://localhost:8000';

export default defineConfig({
  server: {
    port: 5173,
    // 포트가 막혀 있으면 5174로 조용히 밀리지 않고 실패한다.
    // 밀려서 뜨면 컨테이너 프론트(5173, 정적 빌드)를 보면서 "코드를 고쳐도 화면이
    // 안 바뀐다"고 헤매게 된다. 실패하는 편이 원인을 즉시 알려준다.
    strictPort: true,
    // 백엔드를 프록시로 붙여 브라우저 기준 동일 출처를 만든다.
    // 그래서 백엔드에 CORS를 열 필요가 없다 — 프로덕션에서도 nginx가 같은 역할을 한다.
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true, ws: true },
    },
  },
  test: {
    // 검증 대상은 순수 로직(store 패치·표기 변환·백오프)이라 DOM이 필요 없다.
    // 3D와 레이아웃은 브라우저에서 눈으로 확인한다 — 마크업 문자열 단정은 깨지기만 쉽다.
    environment: 'node',
    include: ['tests/**/*.test.ts'],
  },
  // build.target을 지정하지 않는다. Vite 8의 CSS 미니파이어(lightningcss)가 이 값을
  // 브라우저 타겟으로도 해석해서 'ES2022' 같은 JS 타겟을 거부한다. 기본값으로 충분하다.
});
