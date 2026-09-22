#!/usr/bin/env python3
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP = Path(os.environ.get("FORGECORE_APP_ROOT", "/forgecore/app"))
CFG = APP / "config"
RD = CFG / "runners"
ST = APP / "state"
GC = CFG / "forgecore.env"
STORAGE = Path(os.environ.get("FORGECORE_STORAGE_ROOT", "/forgecore/storage"))
STORAGE_DISPLAY = os.environ.get("FORGECORE_STORAGE_DISPLAY", str(STORAGE))
RUNTIME_VERSION = os.environ.get("FORGECORE_RUNTIME_VERSION", "dev")

REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NAME = re.compile(r"^[A-Za-z0-9_.-]{0,63}$")
LABELS = re.compile(r"^[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{10,300}$")

ICON_SVG = r'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 126 126" role="img" aria-labelledby="title"><title id="title">ForgeCore</title><image width="126" height="126" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAH4AAAB+CAIAAABtQTLfAAAmpklEQVR42u19za9kx3XfOVW3X7/PmXlDznA4JBOPHDsjWdFCCiSuYq6YRaCAzsqwNkEWTrwJAgcIAiR/AIEgjhcBEmgRcBER2pmIAgRhgIDUiqZBBlZkaRQmHMccDoccct7M6/fR3fdWnSxO1bmnPu7tfm9GiQ3lotHo1+92972/c+qc3/moKtzbvwZrH94TABiDDaJtJpONKfxiH+1y4bp26TzDgoj8PhFVz+cT+L/N+qAbg1vT6d6lywCwd2Ef/v8Rj9nhwfzkuF0uFu1SIGZ85YWIBDFIqMn+N6TpF/YubG7vCOL8Yyz2kc/KsJDT9EAZ/+xfiGOyMWVYGJnZ4cHs4YNFu3TOW2uqHxGR4IXLz45A7z2xpmdfDe3p+DVZUN9pDH+X/hMRybn8YyZcbhM/3nnKvy0eDnAlNOEcH36IsPIRD8aAd5TAUzltACVrG2w26ygVWp8Yn8zWy6lsYXZ39q5cex4A7t+7Mz85ou5UDNa5jwbo56GAHaClIF2HpqprolBrSq4X4fAlE3kgYsE0090LexcEsaPj2ch3YtXNek/Wmqeefmbvwv7s8ODh5592yxNbcyNaDGzIzicA/kKGbEg2mfpol9UBNkAOTfRgxMNFjyS+sTURJ/KIZhz0upBc10x3rz7zLEP3xeefOueNqfyonUx3Mrw07vfv3Zl9cRd8Z43Rt1o67hHcy3+xepbnGyADNPRtqI7ig/Jx8IAGQJAHRPAeiNiMmPigmgyIPCJSGD0EQBgfNCwzIg8QLtgYQ255+PAL8rT/1DPWWt+1zrvyRuzG5q7cCSJmuB89/Gwl6NqbDzGqDEpCtFhhXfJi5ejJTuA/HRoDRGgMkEHkh/d1vTUMEyWgM+6IfMskzmAcdz5fxIZoEOHk+HA5nz999TogunbZdl12a3Zzey8D6Okr1wT3ZsBNV9HRLqX6X6312Qmada0cNKXloaDR/bNyj1Bx5mzfUpsnwDGgHoxB9AXorOP6/PgO6GcEmM+PlosFoz+fn2Q42OnWrlb5vd0L+089k+Fe4jKE7JBBaIAMkMUw2McFM/6vcSpc0W7EHP34DVqXM5VERLbPtR+jOCySuw7nEgGyfUKDuFicsOVpF/Nlu9T30n+Fc35rOr1y7fnZ4cHh7NCaYGTkVrPQIIOgeqYl3wCx2zwHLyp/8Uy4k/f8bIHsWWgVkZeHAZ/qO5R/8pnZ50XADx/cmx0eXLn2/HSyoa/f6JvkSHX28IFx8zPpmmY+PEQseW1VzsdHEVEgWznsyveRAwiJFQqaMSQPdhNi6DPOo0/LQVcaHW2b8d7PHj5geBOtFxa/NZ0yH1qcPLIGtYq50l56nwsmvsO4l6q6UmczIPhPB5i9X/r8jOCOD4JxTa9qtH7O/qyEYIj9I6I/O/xidniwd2F/o5nIFfZiZJV/+PmnttSOkpZmAarCXYIapwziiBdlZLPn6gsL1CBYIO1RUmsL1V9BY1j3G4P8GFL20rBELwqZytdxr/A/YxEMoih+bnCY888OD6g7lavXyp7fj/cBbn6OuQHBnQ1ORlF6HxCh1IiPG4FMWhaIiBqEEZejzT157wA7T+R950nQVwbNaF0WoNnWy38D1oqTQmIGTSlLDwYQT44fcdpRUDJsbaaTjb0L+/OTY22dtbLnzF1CRGPAe0RsTLDvYuVLNeQX9rETCYYcADQI/CySkDf7XzSG0UdjtKQ7T5kgNXD8Qv60WBh6waFC1SSiMPpN57r79+4AwM72bmR9KqE4PznSJHosqRmVHRHBWu1RxbKfG+sGqZpxHbfmDeahQPgShf64uRdfWnrUxMKUZrO/936ISHzA7xjE+ckRAGxu7xwdzxAxQL+5vTM7PICC2FSjTSKCGOIG0FW8ujILnZoOXxMzjog/ijNmypS7MuQ8WpZBp6wcG3ryntHnNI4F0vkc/lPru2DtCErTPy6/khShsVxRkVswYugBoHN+KIwkdYRED5ENxrFC/PuYDYaUlBqk0kNWZa8lkaeDwBtybII8Wn6hfzrhP95r7jRO6qs5y+qAGBGAlpNvT4TnBOgRkQ19SeOG8jaNQQmUSvLO9pefq4gz6Gvy/cxnaLKkn0UA2v4QkY2JLeE52u6XXCuz1BYhSzet1PqqDCyCT82dWSeSFPuOiA3U49iVIDLcZ00DjJQ3hyIsloF2xcH9eC+Eh2VQRd8CleAmAtAMZ5Sk6j8d5TJrRu4wuz1rEMgDwATDT5dZxtrNyO9hgwSj6fIGPAB0YCaYC7gDIycAQNezESz5KyJqHxCsv7L4EuXaWgYfiQgqqm0RHEWnqmmlep3RpNGbTctpTc3QW/LV6qI+rWrTtRcdAroU+QRIyz5WP3xVSA34Doy+GD6ff5qIPFpyLdqJDmg11cn8raBfrSlaVOFOVEBIwmk/5BUoTQo0AGBrOjtuQKqjPgPdgRlhO5NVI2Bl7p6IWACMvj4/yVKRA2OcaxEATC8A4ZqOPKBNo3fj2DQhsgykfCOxvQ8nmMywZNmIhN2ncZIBADdwY0F9MpX3vnQGIjN2oRY8IjI9136YkZogTZBWlg/lUb5f6kcDvsqvEh8gAVe0POquygK9zRL5qder4D6UShvT+jUrIX0+JLSRAAwktKt3zmo+KTkPrBZD+U4HCckhog3Ta1ynBlywh4Zj+njZ1nQUNMlioX/kABswFr1jTRezQ94RIIMeTP8w7SnN/fzkWBpq8v/p3It+Pc44M8pY2vRSzatKfYaINx0W2VU1kNd+hYBmeQhJKffGlhwAWOq4hQSJ+MG4AwACMdtx1NMeJI/kNfnRuFcF03hPVhHXLPOVuS9RNO0VmmHrUUJQxXq6yv4saJwXhUGgr7Mhr4lQFvHyiwZtR5D7W7QBfSQXfzfYHGODDAAE/XiCKbOY4/anWadOVEVccRisetHMCZega8RtGrc4R9aii3dWlY2WR/hyhC4L/WomSCIvci3Gq/cEgNYCOYWXoM+Ia5crVkibnSrVWRd6W/tAKDzVNR0L3lL6QBrR8Qx0/Wb1X5k8sgHRhIIrdWkWKOOgWUjpAQwG9mrRZOjHjAL2rF9oN/bPZ+rY8Z7WanfNXG7VwjTgq9XwdXT8TId8lmWgv7YcB53yARkHDfzNGOe9YfTBAYAHa4EArUu1kGWgBwEMdBKWefy1tH5l3rG0MBF0PIdh4WNrla0/JRyRgRZDdRB0oOIyhJai/VSNaYw+ABgIziBT/7pSEhGi+Nve+KzC3Rhs1qGVXA+qOoBM2ddX85Vwj5xcSkIcg/xoNgK0+k+QBH0ikgBKo8/W30IOpfa9QjcBLZ92JpvTrCzFaXueJWEE9yeC+FYzqCmnHVW/RMsgGwTZCEjUn/wEAABasCX6bPo5+uHwM0szZOijsToUrqJfEvzc1o+XkzJTI0kVwX0E9PMhXp6zjgxkEJR+uAFqAQBNyAOCA4AWLaMfsGMZYN+21id5qE4uRggiBL9SyfI3q1VeVexSGtPrO9/k+nZ8HbhXykmLQf8Ki4EvRgQgMpgg67sRezEBx+hLAieUPxFEBjL6Wamt+jl+p+5vRy1+Y2qNQbr7pUkZegOeCLSdqeJeIr4S7v1JRUgHLZ5vKIgAqmR0gtCqD03AAcKSjM6gSWmjHwFEdsD+aMa5Jt1sqppe7TrKotMq7hniVbirEK8vj1IY2a+wJHpbFNVfBJCgH6JQDwAb6AHAOQ+m0ervo9H3oagbsjxV61/mGM7AcIYoPOe/ZO5Ahvs46GeC+zEHRzYatpBOCa0SgEafDz0CrDUWfAvKAWQCoJpNhxDievIebSgHin2vdec3Z71zrhFm7lTjrkEfQvza5urK8r25P588RAx8JacdiQnSHFS734kxANBKGhnNBAiiAIYcYe97ES0ExTcAiOAIer9NdaPfrE9p+hoQJnxGcB8HfR241zx/XCqZGHIBFO63p8Wq/LogZAG0kU4vKRBQQPDEdjxWqRh9NjsFk+E4K0vprEgkDPdlDJKWx0f88UeA1n3xwEddIDms2i5te9ETLbN/LcF0njoCRw4AFo6mFqcGADDXZeqDntLN2jS1N6b1WuV1XTSz8qxKJe5DiN+8vl19/9bdk5vXt7/xKztPyiV8fH+ZCO9he+6v+m/zS0G9Htw9vXx968HdH3zczjwmJDJp9HTBMoxWxhsA4I6cEZXn6nNIIeBqfS9xH0Jcn/DKy5ev/9YN+HNzdD/6pHjvr/DzT//+B3/0wE0taHMv6Bs0jsgYcwZy2c8CUF2PQ9aGVX6rwf0JvfSl3RWG+9JkhUkZ1soaBKuPz348X//kj24v1hxAz13ZeOHG9LSj6ZBCB5uO3ntM67cV6JddO1IhWUktXv/Xv9p87dnH0a+7r99+480HPyfQq7Bm5milRbp1N0xC+86vX3njzQe3TwibDXJtnxwWnsN5afJsH5Db/wDLfhMzmoEg3TacFRlY5QHgvR88esyhffWrm/Kc6MXZJboS94/vL8+E+627J4L7zevbL9yYvvXhEQCgb5NUAaIjZH7pybMBGm9Sa9Kx4sFyed5YFbhOkhbJnJZ97+373/j2xcdRfMbrsx/Pr3/t52hkzup4BXE5vvErO++8O3v/IU2axnvf8kzovJshNssAAsLQhNvBaNZCfTZ3owy9GP17c/8f/t39v/P7z8KTOJ4U6Jm+nwn3EnQAeOkrF1+4Mf2X//nTBEFO7wQfizBcWlk3cylaDwPteZo+70/orZ88evH12/+v+MlKj7oO7lW4NQF78Zt7b7z54L8f4sSg5Os8nW2ZCx1SGU0u0ZjS1newVkz06mt3zqewTxz3j24vRhhLibu25kMHm5rX/+QIADpAAPC6V5BITE0/l4upChAC+0s/5mZ1L9w5urG/+3t3z43+yps/N4MsnepZf/elr1wEgH/zhw/vLagDbAm7okIZ64iGcN05wkaTS5M5DKKVeQUd6N+6e7I++t2PPuHHz1XfHx/3m9e3n7uy8b237//ooUNjW0IiMuScaz3YKqkPtBKTjigstD6JZj0kZcZzTPFm9H/7dyu88Mmao/Pp+/rpBA6/r12aMO4/+Ljd2thYuLAMhetznDa41lh07KUAKMUTBDLGZFSoHlLluo+SUUgyxqcdSbby3txz/oDRf+XlOXvdlYifQyRV3Ffqe4n7zevbmeLfvL4tgfe9h+333z/4HzP4ZO6nTQPeC+K+tzNeG/rcXEiTbM0V5z2XvQtGqyhmxe6fUsidMcnJ0H/1tZPv3F5865/dbL727P8FfT+TnckMjig4w/3WTx79dEZ3TuGw9Z0nY3DaWKe8oI/cBsAxMA4MIHjyhpv2QxY5CX/KfM5Y0pgpJhG1gLqHckE4dUFgrPgafUmffe/t++99cCxJsScigCel7+I/n7uyAQDvfXDMiN8+9s75JSQrWrhYperRV103jiCuPBUEw6VrIgIgKUAi4BmgBzVvRJKXpeJn6GsBsPrffPPBKy9fLvMET8S4j2e+hnBnI8768dMZ3Z/TkZNo0Wwo9P2gXubGwGSz1zh3Rh7QAJrSbjTGDPpSPRdSLD6be1F8MTsQqxNaAKz+b314dOu1kI7/xrcvPkGPWk3RrA/6+wf+KNYv8hphDXdfLMhIUh4hn2fnEStvrpOvl6hBLH4H2KQLZ7mIPnR9wUQLQFeXOHL53tv3WQYv3JhWU2aPc6zEnX/3jTcfvP4nR0cdWItM6aRfQYiK9KOVoMfwNV+z1ZNHYxEt+Zg+qy6rMGRwXOjg7PtwsnkNRNRhVHwkp3RfE55yBIgPCNHj2wmNeyIqvzIi5aj7h/e9gJ7grnFIuzBFzTM7IyujsYmHWJ/CHr3Yd5YGSYPpMyLq4pQXoTpi8cfRDynlYgRkAijjmo9uL66vzdzPamoY93/+Hz+7PyebduZA7IvqIqzONNlaSwr33AuCnmnFvf2s8sG71rXee7LTrd3G2r2Ll0+ODt38SJ8hnSeoF/5Aw0vqEaIBcIAO0BAZgx1gB8jNLZ2HzsPEIADMPW6pUO2oo91aa1TbwkdvfX50p2ta2Lna7Fxtjj/r1tf32UnvmY7SMvq1S5Nf++r2P/z3n9w+9lsT41wfpy8oFDFa7zn1KJ0HsopfP08Wkqm8ovLUe1YAIqY3PWK8UgCi93579+LO7oXZo4POucqUZZlWCsA2HJq47IPhNyPbkQgroZvK8YoJWlP9b90FAIC3Q6n26lc316zzjRP5F7+59+prd/7nYXdxw550UDarinfVvX+ZlRdTnJka4TY+VqZATlOtbfUcjhpWLkulhfWTXMsuVxYH6cDEF9irjyMexbrvVzdEZj179+Z+qMvjrQ+PXn3tzmc/npd+eNzUZNbm1t2Ta5cmH91e/PC+v7hhuRlEgG69b0nh7iFj8Z7Cighiaviufdpw4Ml7XvcmduakyzjWSY4pFz+VFTQkp0Zm0hF4tNWFgTT6mvIPoV8VgJYBs9J7c5+hX80Gj+s759nf++D40dJlah4QjxmYtsyFReRcvtwEWhxu9EAkNAhEaMY7jU3C64sVNDinhr5F35JrteLzxAwgT2rBXtF95+iUUARw2tG4ADIZyPM7785G7PuagetbHx5d3EiQ1X1Ozvmlj+tZV5eJSuehO249I89iY24jD4g1cYzpnTCLvNDaPAqoLlFFZkJmgnYi9YEefTSApqW+Y1R0f9z4iABG2rgB4K2fPBoy9ytxZ2sDAHdP8x70cl1/V2THPIHBSmDPt5xwyoqwPE9fGbm1ZjhK7lu9yXsDzgFYO+Hr415OSe/wbzD6E2OYdCYxl7S9q+BryAdkfm5N2j6UqMmGy8QYHbIuyUAWPaU+tg+2JLiRalScPwu17TFIZfBXl0q4l0FciqaxXBZwrvUq4uArWPpo+NBMopNYELL6C30eUf+VR+lsz9pesIVkbVCIiQlq65y3vqvK2Y9cIK8AotpAkondacp+JGlsqvouhMcBygRGD5YF4NOQj7lBCxbIa8sjAtDMZ8j6P05hZBz3F25MtxrMJx3WlDHHPV3tiVU+rHDEq9MlKxBxwx7GyVOc86IVBcJh8YbVAhx5foj6+yLTRFIxIM+krRTAWdWf44BxlR9vL+D/fnkvn9bDo9Na40wDwzky5vLSCqa9q2HFj+IhChkbfoGICMTY01rQkx/08n1RxpW5DrGbPUWLAhAJnRX9/QkdtDjezTmCu35+6SsXhxa4EIPjM9xrXQE9ty7ZCBrgpQJlbctVazibcsRZJCAXIJaWhziBump59MW1YHvqlo7robBrSN/3J/TKy5fPkSnL3OyL39x7fgtOujx85evU2mMwspra8o61RTfDGSUOhLiC19dUO/QOJgKIlkeCXm15XNpF4kyzJCMC0KZJ+15t90vcD1r8za/vX/+tG5mhX7P4J8d7HxwDwO9869K87VLum7AazyEp9RUoHcFy5iAkh5XOEcXOGxIHERtVk6rJWWw9C6CXQeaHFfoDMR1qM5qZ/pXoH7T4G39152//vSuPX1a8dffknXdnL35z79vPTTimbb0X3HnSiCpuEBDpLHKfKYsLkxtFYMqOVowrqGNEHaFO8LN2s4qh7wUAeUIDyAn6OiRxPqxEprNRmd2vxlwa99/+3evMbbS1OavKS1z2zruzf/p3n//2c5N522ncJYUr9r0jyBbcDzBSsugb9dOjSJxAZt8RdExQrJ053dpFxEv7T58cHS5OZqa6xDxSlnQmxLCTBOcrALhQRhS2xpGf9GB86OAkQONlnhFgg8CrI0ue+eES/vq++UcvX/2N3/ua//Qowz3LDJfJYT6e3pt8Psvd75/eXzRL/M2/deXXNpsPP1/+6Qkv+ISUOtROBVB6DVkqLDj1zBJ1qzd/xqR7/HASbSxpPGJ8LOZr+zquZKkxEPm/14udSG7EWlMNep2jIwAA+BtXzHd+/Qr3i3c/+uTc+j7UU/b99w/uPWxfefkyN65+94+PfjZz2w1KZN2RYugqLx+m4kcReR8zCukMcVm9gKKFkWlt1XUl1503m82GLomwTndIsqFzjsXgTGOlY4L8RMlmQfjXLtDv/4O/xPz9sx/PP/rBrcfxq2VjUyiYbBop0L/y8uVXXr78xpsP/sUfPTp02CB0BNkigSGGIqkaoY+1Paphiap/oOeoQL1Mzgy9NLYVBMrFsWTZwaM14Hx0IM57Li4H9J23hVdeED41Cbjz7JQ1gT7rjEBJSt+b+3sfHr31b49e+tLuKy9fvnZp8k/+64PPF9QYzKrQEBYipkpROzbUy3JQXnyshL5FQm0Meg81ylJ0EyZ2v7pJJYCJKTYxPt5OLDgAQGPFCLbef33fMu5nAr06L47/tWbT8h/87Jhrtl+/hP/pHk0xxK6CndSh2Nb7upbHVeiCoQmwZL2uqzOXY9GXXs9djQALpO2+WsmhN/pif9ji6/nm7RrzOgVrfiGNJEMBFJ+pBVCthe1P6NbdEy6XW7Xgtyi+ieizR+W9NU1N4cqMSm3PM5OdmPdclovIVhQ/dvb0q3QL+irNzegHCYnFTy9pYsya9kTj/sabDxjZDFMu9r70lYsM6Er11x83CA2GqCVbm5QU6J5ItfD12xx56N/GcieTmk4n3We6u4GnPCuHAUaXCzjbgwbI816ZjD6PgwR9AKMUP2vIEqbP1mbcgl+7NHnhxvTV1+68fxA+leX97556APjpHz78nW9dGtF3iR72J/Tx/eVBG/eiRLSQJOiZsmNsMfAhTKUkVFVWPNoaTT2h4iqqBgeJPHkgyHAXL59bIZQFImVR8Zz2eBW5LclsgG8p13duxhs/mBT+8L6/slkPzWUliu+/f/CP/+YzAHBzmG5e24Sb13f4d8d3QPR9pTsyGyzWr0/S9GsdOcMhFnXWyhP7sHzUfR3jRdfZOwOLYRc1rf4mcp4lmQ30rfdgDADdunsiWZpxAbzz7uwPfna824QeE+k0KXOfd09D6kbo5kiG57TjzTPqc3SYq/ged4qNNQF9StRuYKnK6no4ma3PPsroc5+JUZvCKHNmNOLMuthiCvqg1k4FjT4BAPyXz+j9f/VnpfKWmHKX5Bb2/6omnDkz8d0/PgqfcpQt9pEdSzDGoO7bZnrT7wPYiyUMaxSzzMvQI0owH80LnY3hAICLhDS1caoBkeXdbxzptZpYFCHHjYkDPVDmMKIPBBsIrfdftAbUaiOnbSXn51SL1Yroz/VrnLUjtQfTSMuN1GBLnXWkq7KxIihAY2hJC8anN1x5iWqM17fLhS4kIqLCebg+nYZazvt+DzdECCvY9SxCM58N8A7AWtN6r/MKI6sca3B166ReXm4d3BMf5uvhZrDy+SgPBdiYQiAMFknwjrWpuESRJHdycpldhDViwkRvod/pDxGoWFcwlacjDHY/RuFxgULITP8SzAb4xBoYw+iXcGe4Q9qvKq8lHS+4l9YmJCzVXkUuNbR9M+XAUFDpGiTUc6dkwzAcIjYVcjnZmIbNNDBpU47jIOYtomPxQKasL8eNgGwazlUyPxF9a4xU6aLvBeklGVdYBrpcynjErGflEUAcwt3pwUB6TlriFwnyaVPKtfYcCFZO1Cc06B31M4CAMvbZr0HS0/Yy8hJNj/vQUZlrE9oDpgHXQTQ+rP76qoaW6y41PWuzKVPzWRm2KlxJw/MCE5nbJB1+an6fGHS12fVAVNXUqSxDW+y3p5YfF4alaHt9v46e7QxlewL6AOA67gsT+Jj+jyh1ZtBL3MWdVnAHzOp/AVKGFQ33DFPq9IZ7PCh7OT7xuFhEPc53pkLle/LE4ZxaccQDVeuNnPDh7Qhcnvbrv1covzONI7C+83YSFhz2Z15wzjkfapPcVlZMdvWeNOgp7oFN2tFugjSTkPZ8VMIrhHXy9QRJMSztpVKt/Bi2tZPYIjhSbjbPHQAmq4Op+CIuapIkG5xpgGgZl/mf1Hdvghasca23EwDgF8a1rOZZn0He2xQzBOUAjduJgYfcfI9kFhODDLpiIkOkErJVpixTnIaiiyzJj2DcuYAJbwQ3jmWfqD958briKnjVzTLczdOcxhBRtS/Imcb6loUU4CZi0K3vlrVyv0+KgZj0R6ZiCDGUpILj/fpsyKJkigtbREL8kchjjI1Wl0oSohs3EctNkG4xlLZPFQSYJNb1gMZiZbfcPNxV6TaxQuMxkU5NQ7oDbWbche9CsUUrqT0wMObHKEaupNc407UKTE0QxgnLMrgGLL4xODZvVnplEU0yIytlPKBoT75VTb8zseFsTx/uRutva+k2HWusNu7FbO5qCbNs8VBWPrQgOAAkMRXFgJBxQCRKL9CGRH0onhsY3ShwROsT/Sbv+g6swrwNFM9S6qlIp0lZmePV4UM2PC/zwvpd3uUwKlpk1Dxj0EUo/hUkQmXiKY1gQ/kwjATsV9UtMsO69YNqO4RBubAueSL0CaYDgVxvZPRY7bknQXQBHZGJ5Rdd8zTqmxyGmVr8Jd6TjEU/ZLJr11bRdFW/AKXpJvWNIbekeQ72QRMmyCIQKSIRG83QoLyuOHCzrtaHqUDFhOiEaOptedL4ghlxHKB92Ss2zqEonUDgCKxaMLLa3m4w1a/adq+qZF8uONybBan8YdxikFQnCAxsIkw0ks6ikpX0MRKQQePX7EjAdEARyC4ZBH3quu8xx5i8Npivi+mA90un3P2Sz4ZCdF9p4izmJMamGxA5QLUxWiVvHoUNBojzkQw02/eS5+gOhSFySVnQU80ohGVCVEt219ZCqoEd47HI9pPKWQebHvNu4rVSY4oEZHT0i8aTtzXd1Bfkoj6V8XCm2tw9Wd11tu8zwF41PfT5l96I94XAfDxlm7lxyjM000N9+26xZusaHIB6/0lvznQ5kPOhiudgOreo3zcy6p1mPjJrxQBlTUjZ0dGgBajSxKLk1KNDiI55iC63xjixIHHY0yAdYJoKCyJPWJLG6qIsw8EyDg0vTP1+IPSxgNBnfvgdxCRxnRpKQzrmRFOysdoGvnoP0PzOS5cfy3siFSlwK/cb+XuZsILaFIXI35OuKXYjBst8GALVtd45Pzs82NzekWJKdis6ZdGrVfR1oT4Q11EQe4X9rkyqaKmYhqwl0A9hVYo3o+Vlyjth0ORVIdI1poKhsw31GBq1ez+bnIbIJ4iFYWQRsLz4QjlMX2ONkEaQKQn49y7sTzampFxkICjpOMjjumiIsPRFsVM3tP9racXmXBqOOIQI+eQSUPcAj3zWDdf8VPCSzCBhIDHdozc1G1i6z/5iFOOS7zBoDBr+s5lMAGB2eMDsOZwxPzkGgO2di973s7ZCmz5/Neo0nJqVCEQQ9iEmokDqVe+ndgwybzqNEEkri9ZQF0Y7OQKhg/xnWdxgrBn0ddZHFT8kU9Ew7athLzr0VXoV12gaMLwOvJxZWRwxzk82d/cu7DPUQeuNweOTIwDYu3S5tO4kYQNFpIucHveJaCmNeA4Kc3xjywmiV7REj9xMx3kE6NGgx4TFFduGsmwcVCaCED9GRyGofdkTj4JYREw630iMPhrc2d7lGjgHjI3kuGeHB2xz2uUCTbLPo1gLpLSvRCo4hVvONuvTWSbiZgsABPREJsbxMSzAcbM+VI3Rc500MWcDGWrfsY8GdOiU978MpBHHjnhiTJinTcvkvG+ajSvXnp8dHpwuAvT91rc8EC7uX03YBREEc5YOgiyHgytycGm+E0OMFcII0A9fA11P8MiOktWU+/B6XqhG8lK6fjC8D3WZWDSpXih9ypZgwSy2IE8M7Pzk2Jhw5SHBZgwezg5nhwdXrj0/2ZjyyBKg6zNAFcNBVaqhfqWMBEL5Km1ne1tLMhGPvDL6PqWJRBUao7/NR28ZZgR66hskdTherJvqe74JJOGS3Cmbo152iV8N4uPZzH1HQhyFzk82pqzybNhzhgMAs4cPAOCZ525ouyZiFXKImKkwwOjAFDdKlTIblQObAB0APxKHnOq4ZCl81hvcx3p5KS9upomamZlCozGqvPhRaYHR46+vLIUlIrAoKRkiQoOs8rOHD/TqfXa6tSujte26yaTZu7DfLpeL+XGWKEZpBhmq+ap/oCofQpHwkQCeJzoqwikOJcx6ZLdNMaNJGJSFp5OFOnKsXCOAJ4kzcVgJ0pJzIAeKI0Y1ZxU0aU1cfJyO5LLQp2dBni5eunrtuV+aHR7MZo80EeihZ+jm8xNr7dNXrx/OZm45l/REZuOwEu5WIouoICYM8L5+k1SKyy2YsIfFYO8ze1LRZ8hQ3WrIwWAEMMhP1B9DKb9/9Om/7KfLi0mpl7oQQCUwuTQEIE9be/sv/NKvzg4Pvvj800wPEuiNMc5537V7Fy9ffurK0fFRt5hjai4ws3dJfKg1GnUgR0ovtMMjfd2FUTKBhxjmrxj4cqRJwXRIbZj/h3l+WwSQlU9jRAR6b8Vet9MMeU7VCiKHFSa6uXvpxi9/GQC++PRu59wY9GJ2XLvY2b2wf/nK/OR42c5FxzF2BI03pEtWTXTCqOw/1ipcvb1JKE1vBMJaG71ycW1CTc1Oh1RJB8rZrTrkRh0/qlJrjzhqo4hpbN0bLwDwjoBgd2//L//ylwHg7p/9r9PFokQsTFnOLPZiuZgfH+5dvHxx/2kiWCxOuEFRxrrWYGGLiJjF2hgzdiQFmLSillj/XHmoKDhUUklYlKuIqK6KQrPTj1MtU51fT7q+rXT66XnJ/DXeUzOZXL7y3LMvfElwNwZ5Ar2+fbu5vVdujGGMWbbd/PgQEPefemZjuuU713VL73zAKuqGSYtZWFTFolYkqWAsHAZGo4SQ5RCLDElvl412aDl5Qt3RQj3N5wpJqvq1FieM/kn8RBlpp+1FntDYC5euPHX1uf2nnpkdHnzy8f9etl0gS5QHCri3f03nNIoRQLs7e1euPc95n9nDB6eLRbc48qnlKjPUaaI41qOVN8vqQaPR6kALEiaZjDz8Wbuk7mvVL00uM6pduUCDTbOxvXNx79LlvQv7AHD/3p2j41mZ006g3tu/Np4FZHnsbO9ubu/w984OD+Ynx/OTo2XaP23cXLpck3uzm8bNYXSbc7sqWndPbIfsJ3BwJRKbzQ1rNhUyDPrxyZG2TlVfSER44fLqXdTk89PJBqfY5Jf+Yh2zw4PxE853X/y185NjDfrKItpa0Osv4lzzdLIBAJONKfzCH+1ysWiXDMsI6GeuzRYEOTS+ny4W8vwLfjDi0rda4pYX1GKXUbMO6OX7yQTzEZY2fBGaqP35xzdjluNXXtsfub934Tn/B2VXntc/UIJzAAAAAElFTkSuQmCC"/></svg>
'''

HTML = r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ForgeCore</title>
<link rel="icon" href="./icon.svg" type="image/svg+xml">
<style>
:root{color-scheme:dark;--bg:#0a0f16;--panel:#101721;--panel2:#0c131c;--border:#283446;--text:#f4f7fb;--muted:#98a5b8;--green:#4ade80;--amber:#f59e0b;--red:#fb7185;--blue:#60a5fa}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 20% -10%,#182334 0,#0a0f16 38%);color:var(--text);font:15px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
main{max-width:1246px;margin:auto;padding:22px 18px 38px}a{color:inherit}.top{display:flex;align-items:center;gap:28px}.logo{width:122px;height:122px;border-radius:22px;overflow:hidden;border:1px solid #334155;background:#090d13;flex:0 0 auto}.logo img{width:100%;height:100%;display:block}.identity{min-width:0}.identity h1{margin:0;font-size:44px;font-weight:700;line-height:1.05;letter-spacing:-1.5px}.identity .subtitle{font-size:21px;font-weight:400;color:#b7c2d4;margin-top:8px}.identity .tagline{font-size:15px;color:var(--muted);margin-top:9px}.top-actions{margin-left:auto;display:flex;align-items:center;gap:10px}
button,.btn,select,input{font:inherit}button,.btn{border:1px solid #344154;border-radius:10px;min-height:40px;padding:9px 14px;background:#182231;color:var(--text);font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}.primary{background:var(--amber);border-color:#a96c05;color:#17110a}.danger{border-color:#713441;color:#ffd6dd;background:#261218}button:disabled{opacity:.55;cursor:wait}
.tabs{display:flex;gap:40px;margin-top:27px;border-bottom:1px solid var(--border)}.tab{background:transparent;border:0;border-radius:0;padding:0 2px 14px;min-height:auto;color:#aeb9ca;font-weight:600}.tab.active{color:#fff;border-bottom:2px solid var(--blue)}.pane{display:none;padding-top:18px}.pane.active{display:block}
.grid3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.card,.wide{border:1px solid var(--border);border-radius:14px;background:linear-gradient(155deg,#111923,#0e151e);padding:20px}.wide{margin-top:14px}.card h2,.wide h2{font-size:16px;font-weight:600;margin:0 0 12px}.labelrow{display:flex;align-items:center;gap:10px}.icon{width:24px;height:24px;display:grid;place-items:center;color:#c7d2e5}.dot{width:11px;height:11px;border-radius:50%;background:var(--green);box-shadow:0 0 0 6px #4ade8014}.dot.off{background:#6b7280;box-shadow:none}.dot.bad{background:var(--red);box-shadow:0 0 0 6px #fb718514}.big{font-size:25px;font-weight:800;margin-top:10px;letter-spacing:-.4px}.good{color:#a7f3d0}.muted,.small{color:var(--muted)}.small{font-size:12px;line-height:1.55}.meta{margin-top:7px;color:#b6c1d2;line-height:1.55}.bar{height:12px;border-radius:999px;background:#202b3c;overflow:hidden;margin:13px 0 8px}.bar span{display:block;height:100%;width:0;background:linear-gradient(90deg,#45c979,#36a764);border-radius:inherit}.split{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:14px}.service,.kv{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 0}.service+.service,.kv+.kv{border-top:1px solid #1d2938}.status-ok{color:var(--green);font-weight:700}.status-muted{color:var(--muted)}.paths{display:grid;gap:8px}.path{display:grid;grid-template-columns:115px 1fr;gap:10px}.path code{color:#abb7c9;overflow-wrap:anywhere}.activity{border:1px solid #1f2b3b;background:#0b1119;border-radius:10px;padding:10px 14px;min-height:105px}.activity-row{display:grid;grid-template-columns:145px 1fr;gap:12px;padding:4px 0}.activity-row time{color:#8795a8;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.empty{color:var(--muted);padding:12px 0}
.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}.section-head h2{margin:0;font-size:18px}.section-head p{margin:4px 0 0;color:var(--muted);font-size:12px}.msg{min-height:18px;margin-top:8px;font-size:12px}.ok{color:var(--green)}.warn{color:#fbbf24}.badtext{color:var(--red)}
form{display:grid;grid-template-columns:1fr 1fr;gap:12px}.full{grid-column:1/-1}label{display:grid;gap:6px;color:#c6d0df;font-size:12px;font-weight:700}input,select{width:100%;padding:10px 11px;border:1px solid #344154;border-radius:9px;background:#0a111a;color:var(--text);font-size:16px;outline:none}input:focus,select:focus{border-color:#9b6914;box-shadow:0 0 0 3px #f59e0b18}.form-actions{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:9px}
.runner{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center;padding:13px;border:1px solid #263347;border-radius:11px;background:#0c131c;margin-top:9px}.repo{font-size:15px;font-weight:800;overflow-wrap:anywhere}
.logbar{display:flex;gap:10px;align-items:end;flex-wrap:wrap}.logbar label{min-width:240px;flex:1}.logbox{margin-top:12px;background:#070b10;border:1px solid #222f40;border-radius:10px;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:520px;overflow:auto;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:#c8d3e2}
.capgrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.cap{border:1px solid #263347;border-radius:11px;background:#0c131c;padding:14px}.cap b{display:block;margin-bottom:5px}.cap span{color:var(--muted);font-size:12px;line-height:1.5}.note{border-left:3px solid var(--amber);background:#17140d;padding:13px 14px;border-radius:8px;color:#d6c6a6;margin-top:14px;font-size:12px;line-height:1.5}
footer{display:flex;justify-content:space-between;gap:12px;color:#778598;margin-top:24px;font-size:12px}
@media(max-width:850px){.grid3,.split{grid-template-columns:1fr 1fr}.split .wide:last-child{grid-column:1/-1}.top{align-items:flex-start}.logo{width:88px;height:88px}.identity h1{font-size:34px}.identity .subtitle{font-size:18px}}
@media(max-width:590px){main{padding:18px 12px 28px}.grid3,.split,.capgrid,form{grid-template-columns:1fr}.split .wide:last-child,.full,.form-actions{grid-column:auto}.top{flex-wrap:wrap}.top-actions{margin-left:0;width:100%}.tabs{gap:16px;overflow:auto}.activity-row{grid-template-columns:1fr}.path{grid-template-columns:1fr}.runner{grid-template-columns:1fr}.logo{width:64px;height:64px}.identity h1{font-size:28px}.identity .subtitle{font-size:15px}footer{flex-direction:column}}
</style>
</head>
<body>
<main>
  <div class="top">
    <div class="logo"><img src="./icon.svg" alt="ForgeCore"></div>
    <div class="identity"><h1>ForgeCore</h1><div class="subtitle">Self-hosted CI runner for your projects</div><div class="tagline">Run GitHub Actions on your own hardware. Simple. Flexible. Yours.</div></div>
    <div class="top-actions"><a class="btn" href="https://github.com/Jojje84/ForgeCore" target="_blank" rel="noopener">Open on GitHub ↗</a></div>
  </div>

  <nav class="tabs" aria-label="ForgeCore sections">
    <button class="tab active" data-tab="overview">Overview</button>
    <button class="tab" data-tab="settings">Settings</button>
    <button class="tab" data-tab="logs">Logs</button>
    <button class="tab" data-tab="about">About</button>
  </nav>

  <section id="overview" class="pane active">
    <div class="grid3">
      <article class="card">
        <h2 class="labelrow"><span id="runnerDot" class="dot off"></span>Runner status</h2>
        <div id="runnerBig" class="big">Starting…</div>
        <div id="runnerMeta" class="meta">Waiting for runner status</div>
      </article>
      <article class="card">
        <h2>Disk usage</h2>
        <div id="diskBig" class="big">—</div>
        <div class="bar"><span id="diskBar"></span></div>
        <div id="diskMeta" class="small">External ForgeCore storage</div>
      </article>
      <article class="card">
        <h2>Last cleanup</h2>
        <div id="cleanupBig" class="big">Not yet</div>
        <div id="cleanupNext" class="meta">Waiting for cleanup status</div>
        <button id="cleanupNow" style="margin-top:12px">Run cleanup now</button>
        <div id="cleanupMsg" class="msg"></div>
      </article>
    </div>

    <div class="split">
      <article class="wide">
        <h2>Services</h2>
        <div class="service"><span>GitHub Runner</span><b id="svcRunner" class="status-muted">Checking…</b></div>
        <div class="service"><span>Runner manager</span><b id="svcManager" class="status-muted">Checking…</b></div>
        <div class="service"><span>Docker Engine</span><b id="svcDocker" class="status-muted">Checking…</b></div>
        <div class="service"><span>Docker Compose</span><b id="svcCompose" class="status-muted">Checking…</b></div>
        <div class="service"><span>QEMU / binfmt</span><b class="status-muted">Optional · not enabled</b></div>
        <div class="service"><span>Dashboard</span><b class="status-ok">Running</b></div>
      </article>
      <article class="wide">
        <h2>Storage locations</h2>
        <div class="paths">
          <div class="path"><span>Runners</span><code id="pathRunners">—</code></div>
          <div class="path"><span>Docker data</span><code id="pathDocker">—</code></div>
          <div class="path"><span>Artifacts</span><code id="pathArtifacts">—</code></div>
          <div class="path"><span>Cache</span><code id="pathCache">—</code></div>
          <div class="path"><span>Logs</span><code id="pathLogs">—</code></div>
        </div>
      </article>
      <article class="wide">
        <h2>Configuration</h2>
        <div class="kv"><span>Cleanup interval</span><span id="cfgCleanup">—</span></div>
        <div class="kv"><span>Cache max age</span><span id="cfgCache">—</span></div>
        <div class="kv"><span>Workspace max age</span><span id="cfgWorkspace">—</span></div>
        <div class="kv"><span>Disk threshold</span><span id="cfgDisk">—</span></div>
        <button class="open-settings" style="margin-top:11px">Edit configuration</button>
      </article>
    </div>

    <article class="wide">
      <div class="section-head"><div><h2>Recent activity</h2><p>Real ForgeCore events from this installation.</p></div><button id="refreshActivity">Refresh</button></div>
      <div id="activity" class="activity"><div class="empty">No activity recorded yet.</div></div>
    </article>
  </section>

  <section id="settings" class="pane">
    <article class="wide">
      <div class="section-head"><div><h2>GitHub runners</h2><p>Add or repair repository runners without SSH. Tokens are cleared from config after registration.</p></div><div><button id="restartRunners">Restart runners</button><div id="restartMsg" class="msg"></div></div></div>
      <div id="runnerList"></div>
      <form id="runnerForm" style="margin-top:16px">
        <label class="full">GitHub repository<input id="repo" placeholder="Jojje84/ForgeCore" required></label>
        <label class="full">Registration token<input id="token" type="password" placeholder="Paste the short-lived token from GitHub" autocomplete="off" required></label>
        <div class="small full">ForgeCore uses the repository name automatically for both the runner name and its single custom label.</div>
        <div class="form-actions"><button class="primary">Connect / repair runner</button><a id="setupLink" class="btn" href="https://github.com/" target="_blank" rel="noopener">Open GitHub runner setup ↗</a></div>
      </form>
      <div id="runnerMsg" class="msg"></div>
    </article>

    <article class="wide">
      <div class="section-head"><div><h2>Cleanup & storage policy</h2><p>These settings are applied by ForgeCore without rebuilding the app.</p></div></div>
      <form id="settingsForm">
        <label>Cleanup interval (days)<input id="setCleanup" type="number" min="1" max="365" required></label>
        <label>Cache max age (days)<input id="setCache" type="number" min="1" max="365" required></label>
        <label>Workspace max age (days)<input id="setWorkspace" type="number" min="1" max="365" required></label>
        <label>Disk cleanup threshold (%)<input id="setThreshold" type="number" min="50" max="99" required></label>
        <label>BuildKit keep storage (GB)<input id="setBuildkit" type="number" min="1" max="1000" required></label>
        <div class="form-actions"><button class="primary">Save configuration</button></div>
      </form>
      <div id="settingsMsg" class="msg"></div>
    </article>
  </section>

  <section id="logs" class="pane">
    <article class="wide">
      <div class="section-head"><div><h2>Logs</h2><p>Persistent ForgeCore logs from the external storage disk.</p></div></div>
      <div class="logbar"><label>Log source<select id="logSource"></select></label><button id="refreshLog">Refresh log</button></div>
      <pre id="logBox" class="logbox">Loading log sources…</pre>
    </article>
  </section>

  <section id="about" class="pane">
    <article class="wide">
      <div class="section-head"><div><h2>What ForgeCore can do</h2><p>The capabilities enabled by this Umbrel package.</p></div></div>
      <div class="capgrid">
        <div class="cap"><b>GitHub self-hosted runners</b><span>Persistent repository-level runners for multiple trusted repositories.</span></div>
        <div class="cap"><b>Private repository checkout</b><span>Authenticated Actions checkout is supported on the self-hosted runner.</span></div>
        <div class="cap"><b>Isolated Docker</b><span>CI jobs use a dedicated Docker engine instead of Umbrel's host Docker socket.</span></div>
        <div class="cap"><b>Docker Compose</b><span>A pinned Compose client is installed into persistent ForgeCore cache.</span></div>
        <div class="cap"><b>Persistent build caches</b><span>Go build/modules, npm, Playwright, Docker CLI and runner tool cache survive restarts.</span></div>
        <div class="cap"><b>External-disk CI storage</b><span>Docker data, runner workspaces, caches, artifacts and logs live on the ForgeCore storage root.</span></div>
        <div class="cap"><b>Automatic cleanup</b><span>Scheduled pruning removes stale CI data and adds extra builder pruning under disk pressure.</span></div>
        <div class="cap"><b>Dashboard administration</b><span>Runner setup/repair, restart, configuration, cleanup status, logs and health are available without SSH.</span></div>
        <div class="cap"><b>Short-lived GitHub tokens</b><span>Registration tokens are cleared from the repository config after registration.</span></div>
        <div class="cap"><b>Optional ARM emulation helper</b><span>The source includes QEMU/binfmt support for ARM64/ARMv7. It is not enabled automatically by the Umbrel package.</span></div>
      </div>
      <div class="note">ForgeCore is intended for trusted repositories and workflows. Persistent self-hosted runners should not execute untrusted fork pull-request code. Keep the ForgeCore dashboard on a trusted local network and do not port-forward its dashboard port to the internet.</div>
    </article>
  </section>

  <footer><span>ForgeCore <b id="version">beta.26</b> · Simple CI. Powerful projects.</span><span id="updated">Waiting for status…</span></footer>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let lastStatus=null,cleanupBaseline=null,restartBaseline=null,runnerRepairBaseline=null;

function setTab(name){
  document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));
  document.querySelectorAll('.pane').forEach(p=>p.classList.toggle('active',p.id===name));
  if(name==='logs') loadLogSources();
}
document.querySelectorAll('.tab').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
document.querySelectorAll('.open-settings').forEach(b=>b.addEventListener('click',()=>setTab('settings')));

async function api(path,opts={}){
  const r=await fetch(path,{cache:'no-store',headers:{'Content-Type':'application/json'},...opts});
  let d={}; try{d=await r.json()}catch{}
  if(!r.ok) throw Error(d.error||('Request failed: '+r.status));
  return d;
}
function rel(epoch){
  if(!epoch)return 'Not yet';
  const sec=Math.max(0,Math.floor(Date.now()/1000-epoch));
  if(sec<60)return 'just now';
  if(sec<3600)return Math.floor(sec/60)+' min ago';
  if(sec<86400)return Math.floor(sec/3600)+' h ago';
  return Math.floor(sec/86400)+' days ago';
}
function until(epoch){const sec=Math.max(0,Math.floor(epoch-Date.now()/1000));if(sec<60)return 'in less than a minute';if(sec<3600)return 'in '+Math.ceil(sec/60)+' min';if(sec<86400)return 'in '+Math.ceil(sec/3600)+' h';return 'in '+Math.ceil(sec/86400)+' days'}
function fmtTime(epoch){return epoch?new Date(epoch*1000).toLocaleString():'—'}
function setDot(id,on,bad=false){const n=$(id);n.className='dot'+(on?'':' off')+(bad?' bad':'')}
function updateRepoLink(){const r=$('repo').value.trim();$('setupLink').href=/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(r)?'https://github.com/'+r+'/settings/actions/runners/new':'https://github.com/'}
$('repo').addEventListener('input',updateRepoLink);

function renderActivity(items){
  $('activity').innerHTML=items&&items.length?items.map(a=>'<div class="activity-row"><time>'+esc(new Date(Number(a.epoch)*1000).toLocaleString())+'</time><span>'+esc(a.message)+'</span></div>').join(''):'<div class="empty">No activity recorded yet.</div>';
}
function renderStatus(s){
  lastStatus=s;
  const runners=s.runners||[],online=runners.filter(r=>r.online).length,first=runners[0];
  const allOnline=runners.length>0&&online===runners.length;
  $('runnerBig').textContent=runners.length?(online+'/'+runners.length+' online'):'Not configured';
  $('runnerBig').className='big'+(allOnline?' good':'');
  $('runnerMeta').innerHTML=first?('Runner: '+esc(first.name||first.repository)+'<br>Repository: '+esc(first.repository)+'<br>Label: '+esc(first.label||first.repository.split('/').pop())+'<br>Mode: '+esc(first.mode||'unknown')+'<br>Phase: '+esc(first.phase||'idle')):'Add a GitHub repository in Settings.';
  setDot('runnerDot',online>0,!!(first&&first.error));
  $('svcRunner').textContent=online>0?'Running':'Offline';$('svcRunner').className=online>0?'status-ok':'status-muted';
  $('svcManager').textContent=s.manager_alive?('Running · '+(s.manager_runtime_version||'unknown')):'Offline / stale';
  $('svcManager').className=s.manager_alive?'status-ok':'status-muted';
  $('svcDocker').textContent=s.docker_online?'Running':'Offline';$('svcDocker').className=s.docker_online?'status-ok':'status-muted';
  $('version').textContent=(s.web_runtime_version||'dev').replace(/^0\.1\.0-/,'');
  $('svcCompose').textContent=s.compose_online?('v'+(s.compose_version||'')):'Unavailable';$('svcCompose').className=s.compose_online?'status-ok':'status-muted';

  const used=Number(s.disk_used_percent||0);
  $('diskBig').textContent=(s.disk_used||'—')+' / '+(s.disk_total||'—');
  $('diskBar').style.width=Math.max(0,Math.min(100,used))+'%';
  $('diskMeta').textContent=used+'% used · '+(s.storage_display||'External ForgeCore storage');

  const last=Number(s.last_cleanup_epoch||0),days=Number(s.cleanup_interval_days||7),next=last+days*86400;
  $('cleanupBig').textContent=rel(last);
  $('cleanupNext').textContent=last?('Next cleanup '+(next<=Date.now()/1000?'is due':until(next))):'Automatic cleanup will establish the schedule.';
  const cb=$('cleanupNow'),cm=$('cleanupMsg');
  if(s.cleanup_running){cb.disabled=true;cb.textContent='Cleanup running…';cm.className='msg warn';cm.textContent='Cleanup is running now.'}
  else if(s.cleanup_pending){cb.disabled=true;cb.textContent='Cleanup queued…';cm.className='msg warn';cm.textContent='Cleanup is queued and will start shortly.'}
  else if(cleanupBaseline!==null&&last>cleanupBaseline){cb.disabled=false;cb.textContent='Run cleanup now';cm.className='msg ok';cm.textContent='Cleanup completed: '+fmtTime(last);cleanupBaseline=null}
  else{cb.disabled=false;cb.textContent='Run cleanup now'}

  const root=s.storage_display||'External ForgeCore storage';
  $('pathRunners').textContent=root+'/runners';
  $('pathDocker').textContent=root+'/docker';
  $('pathArtifacts').textContent=root+'/artifacts';
  $('pathCache').textContent=root+'/cache';
  $('pathLogs').textContent=root+'/logs';
  $('cfgCleanup').textContent=days+' days';
  $('cfgCache').textContent=(s.cache_max_age_days||14)+' days';
  $('cfgWorkspace').textContent=(s.workspace_max_age_days||30)+' days';
  $('cfgDisk').textContent=(s.disk_cleanup_threshold_percent||85)+'%';

  $('setCleanup').value=days;
  $('setCache').value=s.cache_max_age_days||14;
  $('setWorkspace').value=s.workspace_max_age_days||30;
  $('setThreshold').value=s.disk_cleanup_threshold_percent||85;
  $('setBuildkit').value=s.buildkit_keep_storage_gb||50;

  $('runnerList').innerHTML=runners.length?runners.map(r=>'<div class="runner"><div><div class="labelrow"><span class="dot '+(r.online?'':'off')+' '+(r.error?'bad':'')+'"></span><span class="repo">'+esc(r.repository)+'</span></div><div class="small">'+esc(r.online?'Online':r.error?'Needs attention':'Offline')+' · Runner: '+esc(r.name||r.repository.split('/').pop())+' · Label: '+esc(r.label||r.repository.split('/').pop())+' · Mode: '+esc(r.mode||'unknown')+' · Phase: '+esc(r.phase||'idle')+((r.message||r.error)?' · '+esc(r.message||r.error):'')+'</div></div><button class="repair" data-repo="'+esc(r.repository)+'">Repair</button></div>').join(''):'<div class="empty">No repository runner configured yet.</div>';
  document.querySelectorAll('.repair').forEach(b=>b.addEventListener('click',()=>{setTab('settings');$('repo').value=b.dataset.repo;updateRepoLink();$('token').focus()}));

  renderActivity(s.activity||[]);
  const ms=Number(s.manager_started_epoch||0),rb=$('restartRunners'),rm=$('restartMsg');
  if(restartBaseline!==null&&ms>restartBaseline&&s.manager_alive){rb.disabled=false;rb.textContent='Restart runners';rm.className='msg ok';rm.textContent='Runner manager restarted and heartbeat is live.';restartBaseline=null}
  else if(!s.manager_alive){rb.disabled=false;rb.textContent='Restart runners';rm.className='msg badtext';rm.textContent='Runner manager heartbeat is stale. The runner service needs recovery.'}
  {
    const m=$('runnerMsg');
    const phase=first&&first.phase?first.phase:'';
    const message=first&&(first.message||first.error)?(first.message||first.error):'';
    if(first&&first.online){m.className='msg ok';m.textContent='Runner is online in persistent mode.';runnerRepairBaseline=null}
    else if(phase==='error'||phase==='needs-repair'){m.className='msg badtext';m.textContent=message||'Runner needs repair.';runnerRepairBaseline=null}
    else if(['queued','checking','registering','starting','connecting'].includes(phase)){m.className='msg warn';m.textContent=message||('Runner phase: '+phase)}
    else if(runnerRepairBaseline!==null&&ms>runnerRepairBaseline){m.className='msg warn';m.textContent='Runner manager reloaded. Waiting for runner state…'}
  }
  $('updated').textContent='Last updated: '+new Date().toLocaleTimeString();
}
async function refresh(){try{renderStatus(await api('/api/status'))}catch(e){$('updated').textContent='Waiting for ForgeCore runtime…'}}
$('refreshActivity').addEventListener('click',refresh);

$('cleanupNow').addEventListener('click',async()=>{
  const b=$('cleanupNow'),m=$('cleanupMsg'); cleanupBaseline=Number(lastStatus?.last_cleanup_epoch||0);
  b.disabled=true;b.textContent='Cleanup queued…';m.className='msg warn';m.textContent='Sending cleanup request…';
  try{await api('/api/cleanup',{method:'POST',body:'{}'});setTimeout(refresh,800)}
  catch(e){cleanupBaseline=null;b.disabled=false;b.textContent='Run cleanup now';m.className='msg badtext';m.textContent=e.message}
});
$('restartRunners').addEventListener('click',async()=>{
  const b=$('restartRunners'),m=$('restartMsg');restartBaseline=Number(lastStatus?.manager_started_epoch||0);
  b.disabled=true;b.textContent='Restarting…';m.className='msg warn';m.textContent='Waiting for runner manager…';
  try{await api('/api/reload',{method:'POST',body:'{}'})}
  catch(e){restartBaseline=null;b.disabled=false;b.textContent='Restart runners';m.className='msg badtext';m.textContent=e.message}
});
$('runnerForm').addEventListener('submit',async ev=>{
  ev.preventDefault();const m=$('runnerMsg');runnerRepairBaseline=Number(lastStatus?.manager_started_epoch||0);m.className='msg warn';m.textContent='Saving token and reloading runner manager…';
  try{
    await api('/api/runners',{method:'POST',body:JSON.stringify({repository:$('repo').value.trim(),token:$('token').value.trim()})});
    $('token').value='';m.className='msg warn';m.textContent='Repair request saved. Status will persist after refresh.';setTimeout(refresh,500)
  }catch(e){runnerRepairBaseline=null;m.className='msg badtext';m.textContent=e.message}
});
$('settingsForm').addEventListener('submit',async ev=>{
  ev.preventDefault();const m=$('settingsMsg');m.className='msg warn';m.textContent='Saving configuration…';
  try{
    await api('/api/settings',{method:'POST',body:JSON.stringify({cleanup_interval_days:Number($('setCleanup').value),cache_max_age_days:Number($('setCache').value),workspace_max_age_days:Number($('setWorkspace').value),disk_cleanup_threshold_percent:Number($('setThreshold').value),buildkit_keep_storage_gb:Number($('setBuildkit').value)})});
    m.className='msg ok';m.textContent='Configuration saved.';setTimeout(refresh,500)
  }catch(e){m.className='msg badtext';m.textContent=e.message}
});

async function loadLogSources(){
  try{
    const d=await api('/api/logs');const sel=$('logSource'),current=sel.value;
    sel.innerHTML=(d.sources||[]).map(x=>'<option value="'+esc(x.id)+'">'+esc(x.label)+'</option>').join('');
    if(current&&[...sel.options].some(o=>o.value===current))sel.value=current;
    await loadLog();
  }catch(e){$('logBox').textContent=e.message}
}
async function loadLog(){
  const id=$('logSource').value;if(!id){$('logBox').textContent='No persistent logs are available yet.';return}
  try{const d=await api('/api/logs?kind='+encodeURIComponent(id));$('logBox').textContent=d.text||'Log is empty.';$('logBox').scrollTop=$('logBox').scrollHeight}catch(e){$('logBox').textContent=e.message}
}
$('refreshLog').addEventListener('click',loadLog);

updateRepoLink();refresh();setInterval(refresh,5000);
</script>
</body>
</html>'''

def env(path):
    out = {}
    try:
        for raw in path.read_text().splitlines():
            s = raw.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            v = v.strip()
            out[k.strip()] = v[1:-1] if len(v) > 1 and v[0] == v[-1] == '"' else v
    except OSError:
        pass
    return out

def slug(repo):
    return re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")

def int_setting(config, key, default):
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default

def settings():
    c = env(GC)
    return {
        "cleanup_interval_days": max(1, int_setting(c, "CLEANUP_INTERVAL_HOURS", 168) // 24),
        "cache_max_age_days": max(1, int_setting(c, "CACHE_MAX_AGE_DAYS", 14)),
        "workspace_max_age_days": max(1, int_setting(c, "WORKSPACE_MAX_AGE_DAYS", 30)),
        "disk_cleanup_threshold_percent": max(1, min(100, int_setting(c, "DISK_CLEANUP_THRESHOLD_PERCENT", 85))),
        "buildkit_keep_storage_gb": max(1, int_setting(c, "BUILDKIT_KEEP_STORAGE_GB", 50)),
        "compose_version": c.get("COMPOSE_VERSION", "5.5.1"),
    }

def runners():
    out = []
    for p in sorted(RD.glob("*.env")):
        if p.name == "runner.env.example":
            continue
        c = env(p)
        repo = c.get("REPOSITORY", "")
        if not REPO.fullmatch(repo):
            continue
        s = slug(repo)
        ep = ST / f"runner-{s}.error"
        np = ST / f"runner-{s}.name"
        runtime_path = ST / f"runner-{s}.runtime.json"
        runner_dir = STORAGE / "runners" / s
        settings_file = runner_dir / ".runner"
        er = ep.read_text(encoding="utf-8", errors="replace").strip() if ep.exists() else ""
        name = c.get("NAME", "")
        if np.exists():
            name = np.read_text(encoding="utf-8", errors="replace").strip()

        mode = "unregistered"
        phase = "idle"
        message = ""
        runtime = {}
        try:
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runtime = {}

        if isinstance(runtime, dict):
            phase = str(runtime.get("phase", phase))
            message = str(runtime.get("message", ""))
            runtime_mode = str(runtime.get("mode", "")).strip()
            if runtime_mode:
                mode = runtime_mode

        if mode in ("", "unregistered", "unknown") and settings_file.exists():
            try:
                identity = json.loads(settings_file.read_text(encoding="utf-8-sig", errors="strict"))
                mode = "ephemeral" if bool(identity.get("Ephemeral", identity.get("ephemeral", False))) else "persistent"
            except (OSError, UnicodeError, json.JSONDecodeError, AttributeError):
                mode = "unreadable"

        if er:
            message = er
            if phase not in ("registering", "starting", "connecting"):
                phase = "error"

        online = (ST / f"runner-{s}.online").exists() and phase == "online"
        out.append({
            "repository": repo,
            "name": name,
            "label": repo.rsplit("/", 1)[-1],
            "mode": mode,
            "phase": phase,
            "message": message,
            "online": online,
            "error": er,
        })
    return out

def append_activity(kind, message):
    ST.mkdir(parents=True, exist_ok=True)
    record = {"epoch": int(__import__("time").time()), "type": kind, "message": message}
    with (ST / "activity.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")

def activity(limit=12):
    path = ST / "activity.log"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict) and "epoch" in item and "message" in item:
                out.append(item)
        except json.JSONDecodeError:
            continue
    return list(reversed(out))

def status():
    x = {
        "runner_online": False,
        "runner_name": "Runner not configured",
        "docker_online": False,
        "compose_online": False,
        "disk_used": "—",
        "disk_total": "—",
        "disk_used_percent": 0,
    }
    try:
        x.update(json.loads((ST / "status.json").read_text()))
    except (OSError, json.JSONDecodeError):
        pass
    x.update(settings())
    now = int(__import__("time").time())
    try:
        status_epoch = int(x.get("status_epoch", 0))
    except (TypeError, ValueError):
        status_epoch = 0
    x["manager_alive"] = status_epoch > 0 and (now - status_epoch) <= 20
    x["manager_runtime_version"] = str(x.get("runtime_version", "unknown"))
    x["web_runtime_version"] = RUNTIME_VERSION
    x["runners"] = runners()
    x["storage_display"] = STORAGE_DISPLAY
    x["activity"] = activity()
    try:
        x["last_cleanup_epoch"] = int((ST / "last-cleanup-epoch").read_text().strip())
    except (OSError, ValueError):
        x["last_cleanup_epoch"] = 0
    x["cleanup_pending"] = (ST / "cleanup-now.request").exists()
    x["cleanup_running"] = (ST / "cleanup-running").exists()
    return x

def origin_ok(handler):
    origin = handler.headers.get("Origin")
    host = handler.headers.get("Host", "")
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.netloc == host and parsed.scheme in ("http", "https")

def write_env_updates(path, updates):
    lines = []
    seen = set()
    try:
        original = path.read_text().splitlines()
    except OSError:
        original = []
    for raw in original:
        stripped = raw.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                lines.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        lines.append(raw)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)

def save_settings(data):
    def bounded(key, lo, hi):
        try:
            value = int(data.get(key))
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number.")
        if value < lo or value > hi:
            raise ValueError(f"{key} must be between {lo} and {hi}.")
        return value
    cleanup_days = bounded("cleanup_interval_days", 1, 365)
    cache_days = bounded("cache_max_age_days", 1, 365)
    workspace_days = bounded("workspace_max_age_days", 1, 365)
    threshold = bounded("disk_cleanup_threshold_percent", 50, 99)
    keep_gb = bounded("buildkit_keep_storage_gb", 1, 1000)
    write_env_updates(GC, {
        "CLEANUP_INTERVAL_HOURS": cleanup_days * 24,
        "CACHE_MAX_AGE_DAYS": cache_days,
        "WORKSPACE_MAX_AGE_DAYS": workspace_days,
        "DISK_CLEANUP_THRESHOLD_PERCENT": threshold,
        "BUILDKIT_KEEP_STORAGE_GB": keep_gb,
    })
    append_activity("settings", "ForgeCore configuration updated")

def save_runner(data):
    repo = str(data.get("repository", "")).strip()
    token = str(data.get("token", "")).strip()
    if not REPO.fullmatch(repo):
        raise ValueError("Repository must look like owner/repository.")
    if not TOKEN.fullmatch(token):
        raise ValueError("Enter a fresh GitHub self-hosted runner registration token.")
    s = slug(repo)
    dst = RD / f"{s}.env"
    for candidate in RD.glob("*.env"):
        if candidate.name != "runner.env.example" and env(candidate).get("REPOSITORY", "") == repo:
            dst = candidate
            break
    tmp = dst.with_name("." + dst.name + ".tmp")
    tmp.write_text(
        f'REPOSITORY="{repo}"\n'
        f'REGISTRATION_TOKEN="{token}"\n'
    )
    os.chmod(tmp, 0o600)
    os.replace(tmp, dst)
    ST.mkdir(parents=True, exist_ok=True)
    runtime_path = ST / f"runner-{s}.runtime.json"
    runtime_tmp = runtime_path.with_name("." + runtime_path.name + ".tmp")
    runtime_tmp.write_text(
        json.dumps(
            {
                "epoch": int(__import__("time").time()),
                "repository": repo,
                "phase": "queued",
                "mode": "unknown",
                "message": "Repair request saved; waiting for runner manager",
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    os.replace(runtime_tmp, runtime_path)
    append_activity("runner", f"Runner registration requested for {repo}")
    (ST / "reload-runners.request").touch()

def tail_text(path, max_bytes=65536):
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, 2)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""

def log_sources():
    sources = []
    mapping = [
        ("runner-manager", "Runner manager", STORAGE / "logs" / "runner-manager.log"),
        ("cleanup", "Cleanup", STORAGE / "logs" / "cleanup.log"),
    ]
    for ident, label, path in mapping:
        if path.exists():
            sources.append({"id": ident, "label": label})
    for p in sorted((STORAGE / "logs").glob("runner-*.log")):
        if p.name == "runner-manager.log":
            continue
        ident = "runner:" + p.stem[len("runner-"):]
        sources.append({"id": ident, "label": "Runner · " + p.stem[len("runner-"):].replace("-", "/")})
    return sources

def resolve_log(kind):
    if kind == "runner-manager":
        return STORAGE / "logs" / "runner-manager.log"
    if kind == "cleanup":
        return STORAGE / "logs" / "cleanup.log"
    if kind.startswith("runner:"):
        slug_value = kind.split(":", 1)[1]
        if re.fullmatch(r"[a-z0-9-]+", slug_value):
            return STORAGE / "logs" / f"runner-{slug_value}.log"
    return None

class Handler(BaseHTTPRequestHandler):
    server_version = "ForgeCoreDashboard/0.2"

    def log_message(self, fmt, *args):
        print("[forgecore-web] " + fmt % args, flush=True)

    def send_json(self, code, data):
        payload = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_svg(self):
        payload = ICON_SVG.encode()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_html(self):
        payload = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html()
        elif parsed.path == "/icon.svg":
            self.send_svg()
        elif parsed.path == "/api/status":
            self.send_json(200, status())
        elif parsed.path == "/api/logs":
            kind = parse_qs(parsed.query).get("kind", [""])[0]
            if not kind:
                self.send_json(200, {"sources": log_sources()})
                return
            path = resolve_log(kind)
            if not path:
                self.send_json(404, {"error": "Unknown log source"})
                return
            self.send_json(200, {"kind": kind, "text": tail_text(path)})
        elif parsed.path == "/health":
            current = status()
            self.send_json(200, {
                "ok": True,
                "web_runtime_version": RUNTIME_VERSION,
                "manager_alive": bool(current.get("manager_alive")),
                "manager_runtime_version": current.get("manager_runtime_version", "unknown"),
            })
        else:
            self.send_json(404, {"error": "Not found"})

    def do_POST(self):
        if not origin_ok(self):
            self.send_json(403, {"error": "Origin rejected"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self.send_json(415, {"error": "JSON required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 0 or length > 8192:
            self.send_json(413, {"error": "Request too large"})
            return
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return
        try:
            path = urlparse(self.path).path
            if path == "/api/runners":
                save_runner(data)
            elif path == "/api/settings":
                save_settings(data)
            elif path == "/api/reload":
                append_activity("runner", "Runner manager restart requested")
                (ST / "reload-runners.request").touch()
            elif path == "/api/cleanup":
                append_activity("cleanup", "Cleanup requested")
                (ST / "cleanup-now.request").touch()
            else:
                self.send_json(404, {"error": "Not found"})
                return
            self.send_json(202, {"ok": True})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except OSError:
            self.send_json(500, {"error": "ForgeCore could not write its app data."})

def main():
    RD.mkdir(parents=True, exist_ok=True)
    ST.mkdir(parents=True, exist_ok=True)
    print("[forgecore-web] dashboard listening on :8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

if __name__ == "__main__":
    main()
