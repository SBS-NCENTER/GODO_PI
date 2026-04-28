<script lang="ts">
  import { navigate } from '$lib/router';
</script>

<div class="card" data-testid="not-found">
  <h2>404</h2>
  <p>페이지를 찾을 수 없습니다.</p>
  <button class="primary" onclick={() => navigate('/')}>Dashboard로</button>
</div>

<style>
  h2 {
    margin-top: 0;
  }
</style>
