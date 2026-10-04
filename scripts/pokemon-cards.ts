/*
 * Pokémon card database for Card Vault.
 *
 * Usage: bun scripts/pokemon-cards.ts CARDS_DATABASE_DIR OUT_FILE [ASSETS_JSON] [CARDMARKET_SINGLES_JSON]
 *
 * Reads a checkout of TCGdex's open card database (github.com/tcgdex/cards-database, MIT licence)
 * and writes one compact file with every English and Japanese card: its set, number, name, rarity,
 * whether TCGdex has a picture of it, and the Cardmarket product id of each version. The app uses
 * those ids to find a card's Cardmarket price directly.
 *
 * ASSETS_JSON is TCGdex's list of available pictures (assets.tcgdex.net/datas.json); without it every
 * card is marked as possibly having a picture and the app simply hides pictures that fail to load.
 *
 * Each card also carries its regulation mark ("*" for basic Energy, which is always allowed), and the file
 * carries TCGdex's current Standard format (the legal regulation marks and banned cards, meta/legals.ts),
 * so the app can show which cards are Standard legal.
 *
 * Each card also says whether it is an original print (field 8: 1 = the card's first release, 0 = a reprint,
 * left out when the dates can't tell). Two cards are the same card when name, HP, attacks, abilities and
 * effect text match; English and Japanese are counted separately. Promo sets only count as the first release
 * when the card was never in a regular set, because a promo set's date is the date of its first promo.
 *
 * CARDMARKET_SINGLES_JSON is Cardmarket's Pokémon singles list (products_singles_6.json). TCGdex hasn't
 * linked every card to Cardmarket yet, so cards it left without a link are matched here by English name
 * within the same set, in number order. Those links are marked as matched by name (last field 1).
 */
import { Glob } from "bun"
import path from "node:path"

const [rootArg, outFile, assetsFile, singlesFile] = process.argv.slice(2)
const root = path.resolve(rootArg)
const assets = assetsFile ? await Bun.file(assetsFile).json().catch(() => null) : null

type Out = { sets: any[], cards: any[] }
const out: Out = { sets: [], cards: [] }
const setIdx = new Map<string, number>()
const STAMPS = new Set<string>()
const PRINT_KEY: string[] = []      // per card: what makes two cards the same card, for finding reprints

// letters and digits only, any script, so small wording or punctuation changes don't split a card
const squash = (v: any) => String(v ?? "").toLowerCase().normalize("NFKC").replace(/[^\p{L}\p{N}]/gu, "")
function printKey(card: any, lang: string, name: string): string {
	const t = (v: any) => squash(text(v, lang) || text(v, "en"))
	const attacks = (card.attacks || []).map((a: any) => t(a.name) + ":" + squash(a.damage)).join(",")
	const abilities = (card.abilities || []).map((a: any) => t(a.name)).join(",")
	const effect = card.category === "Pokemon" ? "" : t(card.effect)
	return [lang, squash(card.category), squash(name), squash(card.hp), attacks, abilities, effect].join("|")
}

const text = (v: any, lang: string) => v == null ? "" : typeof v === "string" ? v : (v[lang] ?? "")
const date = (v: any, lang: string) => !v ? "" : typeof v === "string" ? v : (v[lang] ?? "")

function variantList(card: any): any[] {
	// returns [cardmarketId, type, size, stamps, subtype] for each version Cardmarket lists
	const list: any[] = []
	if (Array.isArray(card.variants)) {
		for (const v of card.variants) {
			if (v.languages && !v.languages.includes(card.__lang)) continue
			const cm = v.thirdParty?.cardmarket
			if (!cm) continue
			for (const s of v.stamp || []) STAMPS.add(s)
			list.push([cm, v.type || "", v.size === "jumbo" ? "jumbo" : "", (v.stamp || []).join(","), v.subtype || "", v.foil || ""])
		}
	}
	const own = card.thirdParty?.cardmarket
	if (own && !list.some(v => v[0] === own)) list.unshift([own, "", "", "", "", ""])
	return list
}

async function load(dir: string, lang: "en" | "ja") {
	const glob = new Glob("*/*/*.ts")
	let n = 0, priced = 0, bad = 0
	for await (const rel of glob.scan({ cwd: path.join(root, dir) })) {
		const file = path.join(root, dir, rel)
		let card: any
		try { card = (await import(file)).default } catch (e) { bad++; continue }
		if (!card || !card.set || !card.name) continue
		const name = text(card.name, lang)
		if (!name) continue
		const set = card.set
		const serie = set.serie || {}
		let si = setIdx.get(lang + "|" + set.id)
		if (si === undefined) {
			si = out.sets.length
			setIdx.set(lang + "|" + set.id, si)
			out.sets.push([
				set.id, lang, text(set.name, lang) || text(set.name, "en"),
				(set.abbreviations && set.abbreviations.official) || "",
				set.thirdParty?.cardmarket || 0,
				date(set.releaseDate, lang),
				(set.cardCount && set.cardCount.official) || 0,
				serie.id || "", text(serie.name, lang) || text(serie.name, "en"),
			])
		}
		const localId = path.basename(rel, ".ts")
		card.__lang = lang
		const variants = variantList(card)
		const pic = assets ? (assets[lang]?.[serie.id]?.[set.id]?.[localId] ? 1 : 0) : 1
		const reg = card.energyType === "Normal" ? "*" : (card.regulationMark || "")
		out.cards.push([si, localId, name, card.rarity || "", (card.category || "").charAt(0), pic, variants, reg])
		PRINT_KEY.push(printKey(card, lang, name))
		n++; if (variants.length) priced++
	}
	console.log(`${lang}: ${n} cards, ${priced} with Cardmarket ids, ${bad} files unreadable`)
}

await load("data", "en")
await load("data-asia", "ja")

if (singlesFile) {
	const singles = (await Bun.file(singlesFile).json()).products as any[]
	const norm = (s: string) => String(s || "").replace(/\s*\[.*\]\s*$/, "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]/g, "")
	const linked = new Set<number>()
	for (const c of out.cards) for (const v of c[6]) linked.add(v[0])
	const setsByExp = new Map<number, number[]>()
	out.sets.forEach((st, i) => { if (st[4] && st[1] === "en") (setsByExp.get(st[4]) || setsByExp.set(st[4], []).get(st[4])!).push(i) })
	const open = new Map<string, any[]>()      // exp|name -> TCGdex cards without a Cardmarket link
	for (const c of out.cards) {
		if (c[6].length) continue
		const exp = out.sets[c[0]][4]
		if (!exp || !setsByExp.has(exp)) continue
		const k = exp + "|" + norm(c[2]);
		(open.get(k) || open.set(k, []).get(k)!).push(c)
	}
	const num = (id: string) => { const m = String(id).match(/\d+/); return m ? parseInt(m[0], 10) : 0 }
	for (const list of open.values()) list.sort((a, b) => num(a[1]) - num(b[1]) || String(a[1]).localeCompare(String(b[1])))
	const products = new Map<string, any[]>()
	for (const p of singles.slice().sort((a, b) => a.idProduct - b.idProduct)) {
		if (linked.has(p.idProduct) || !setsByExp.has(p.idExpansion)) continue
		const k = p.idExpansion + "|" + norm(p.name);
		(products.get(k) || products.set(k, []).get(k)!).push(p)
	}
	let matched = 0
	for (const [k, cards] of open) {
		const ps = products.get(k)
		if (!ps) continue
		for (let i = 0; i < Math.min(cards.length, ps.length); i++) { cards[i][6].push([ps[i].idProduct, "", "", "", "", "", 1]); matched++ }
	}
	console.log(`matched ${matched} more cards to Cardmarket by name`)
}
// original prints: the earliest dated regular set wins; promo sets only when the card has no regular print
{
	const promo = (st: any[]) => /promo|プロモ/i.test(st[2]) || /(^|-)P$/i.test(st[0]) || /^(svp|swshp|smp|xyp|bwp|hgssp|dpp|np|wp|basep)$/i.test(st[0])
	const groups = new Map<string, number[]>()
	out.cards.forEach((c, i) => {
		if (out.sets[c[0]][7] === "tcgp") return        // Pokémon TCG Pocket is digital only
		const k = PRINT_KEY[i]; (groups.get(k) || groups.set(k, []).get(k)!).push(i)
	})
	let orig = 0, re = 0
	for (const list of groups.values()) {
		const dated = list.filter(i => /^\d{4}-\d{2}-\d{2}/.test(out.sets[out.cards[i][0]][5]))
		const regular = dated.filter(i => !promo(out.sets[out.cards[i][0]]))
		const pool = regular.length ? regular : dated
		if (!pool.length) continue
		const day = (i: number) => String(out.sets[out.cards[i][0]][5]).slice(0, 10)
		const first = pool.map(day).sort()[0]
		for (const i of list) {
			if (!dated.includes(i)) continue               // no date: can't tell
			const isOrig = pool.includes(i) && day(i) === first
			out.cards[i][8] = isOrig ? 1 : 0
			if (isOrig) orig++; else re++
		}
	}
	console.log(`original prints: ${orig}, reprints: ${re}`)
}
// the Standard format as TCGdex keeps it: legal regulation marks, and sets or cards left out of it
let standard: any = null
try {
	const legals = await import(path.join(root, "meta", "legals.ts"))
	const s = legals.standard
	standard = { marks: s.includes.regulationMark || [], sets: s.includes.sets || [], excludeSets: s.excludes.sets || [], excludeCards: s.excludes.cards || [] }
	console.log("Standard regulation marks:", standard.marks.join(", "))
} catch (e) { console.log("No Standard format list:", e) }
const doc = { date: new Date().toISOString(), source: "TCGdex cards-database (MIT)", standard, ...out }
await Bun.write(outFile, JSON.stringify(doc))
console.log(`sets ${out.sets.length}, cards ${out.cards.length}, stamps: ${[...STAMPS].join(" ")}`)
