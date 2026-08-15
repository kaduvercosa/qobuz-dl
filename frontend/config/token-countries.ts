export interface CountryToken {
  name: string;
  code: string;
  token: string;
  flag?: string;
}

export const COUNTRIES: CountryToken[] = [
  { name: "United States", code: "US", token: "us_token_placeholder" },
  { name: "United Kingdom", code: "GB", token: "gb_token_placeholder" },
  { name: "France", code: "FR", token: "fr_token_placeholder" },
  { name: "Germany", code: "DE", token: "de_token_placeholder" },
  { name: "Italy", code: "IT", token: "it_token_placeholder" },
  { name: "Spain", code: "ES", token: "es_token_placeholder" },
  { name: "Netherlands", code: "NL", token: "nl_token_placeholder" },
  { name: "Brazil", code: "BR", token: "br_token_placeholder" },
  { name: "Canada", code: "CA", token: "ca_token_placeholder" },
  { name: "Japan", code: "JP", token: "jp_token_placeholder" },
  { name: "Australia", code: "AU", token: "au_token_placeholder" },
  { name: "Portugal", code: "PT", token: "pt_token_placeholder" }
];
