Pasta reservada para imagens estáticas do app (logo, banner, avatar padrão).

As fotos dos lutadores NÃO ficam aqui: elas são carregadas dinamicamente pela
interface (interface.py -> load_fighter_image) a partir da URL real cadastrada
no campo `image_url` de cada lutador no banco de dados, quando essa URL existe.
Isso evita incluir no repositório imagens cuja licença de uso não foi
verificada.
