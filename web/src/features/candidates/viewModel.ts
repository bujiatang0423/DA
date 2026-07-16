export function bucketLabel(bucket:string):string{return ({executable:"可执行",watchlist:"观察",excluded:"排除"} as Record<string,string>)[bucket] ?? bucket}
