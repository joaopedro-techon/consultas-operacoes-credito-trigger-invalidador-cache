-- Cópia do script de gravação por bloco da API de consultas (ScriptValkey.GRAVAR_POR_BLOCO, ADR-0019), para o teste
-- de contrato. Se mudar lá, atualizar aqui.
-- KEYS[1]: o hash; ARGV[1]: TTL em ms; ARGV[2..]: trios bloco/versão em epoch ms/valor.
local criado = redis.call('EXISTS', KEYS[1]) == 0
local gravados = 0
for i = 2, #ARGV, 3 do
  local bloco = ARGV[i]
  local versao = tonumber(ARGV[i + 1])
  local atual = redis.call('HMGET', KEYS[1], 'v:' .. bloco, 'm:' .. bloco, bloco)
  local versaoAtual = atual[1] and tonumber(atual[1])
  local manter = versaoAtual and (versaoAtual > versao
    or (versaoAtual == versao and not atual[2] and atual[3]))
  if not manter then
    redis.call('HSET', KEYS[1], bloco, ARGV[i + 2], 'v:' .. bloco, ARGV[i + 1])
    redis.call('HDEL', KEYS[1], 'm:' .. bloco)
    gravados = gravados + 1
  end
end
if criado and gravados > 0 then
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
end
return gravados
