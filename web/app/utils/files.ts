/** Read one picked file as base64, without the `data:` prefix the API rejects. */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = String(reader.result ?? '')
      resolve(result.slice(result.indexOf(',') + 1))
    }
    reader.onerror = () => reject(reader.error ?? new Error('The file could not be read.'))
    reader.readAsDataURL(file)
  })
}

export async function filesToBase64(files: File[]): Promise<{ name: string; data_base64: string }[]> {
  return Promise.all(
    files.map(async (file) => ({ name: file.name, data_base64: await fileToBase64(file) })),
  )
}
