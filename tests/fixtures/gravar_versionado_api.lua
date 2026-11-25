-- Cópia do script de gravação da API de consultas (ScriptValkey.GRAVAR_VERSIONADO, ADR-0018), para o teste de
-- contrato. Se mudar lá, atualizar aqui.
-- KEYS[1]: o hash; ARGV[1]: versão em epoch ms; ARGV[2]: TTL em ms; ARGV[3..]: pares campo/valor.
local atual = redis.call('HMGET', KEYS[1], 'versao', 'marcador')
local versao = tonumber(ARGV[1])
local versaoAtual = atual[1] and tonumber(atual[1])
if versaoAtual then
  if versaoAtual > versao then
    return 0
  end
  if versaoAtual == versao and not atual[2] then
    redis.call('HSET', KEYS[1], unpack(ARGV, 3))
    return 2
  end
end
redis.call('DEL', KEYS[1])
redis.call('HSET', KEYS[1], 'versao', ARGV[1], unpack(ARGV, 3))
redis.call('PEXPIRE', KEYS[1], ARGV[2])
return 1
