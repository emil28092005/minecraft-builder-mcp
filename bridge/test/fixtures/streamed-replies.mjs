export const greetingChunks = ['Пр', 'ивет! ', 'Что пост', 'роим?'];
export const followUpChunks = ['По', 'нятно. ', 'Проверяю ', 'осве', 'щение'];
export const longReply = 'Осматриваю зал. ' + Array.from({ length: 28 }, (_, i) =>
  `Арка${i + 1} цела, фонарь${i + 1} 🏮 установлен ровно`
).join(', ') + '. Проверка завершена';
export const overlongWord = 'А'.repeat(239) + '🏮'.repeat(150) + 'конец';

export function tokenChunks(text) {
  const sizes = [2, 3, 7, 4, 11];
  const chunks = [];
  for (let offset = 0, i = 0; offset < text.length; i++) {
    const end = Math.min(text.length, offset + sizes[i % sizes.length]);
    chunks.push(text.slice(offset, end));
    offset = end;
  }
  return chunks;
}
