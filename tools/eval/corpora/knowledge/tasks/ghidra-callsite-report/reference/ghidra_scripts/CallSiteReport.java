// Writes the call sites of the named functions as JSON.
// Headless: -postScript CallSiteReport.java <out.json> <name> [<name> ...]
//@category Analysis
import java.io.File;
import java.io.FileWriter;
import java.io.Writer;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;

public class CallSiteReport extends GhidraScript {

    private static final class Site {
        final Address at;
        final String caller;
        Site(Address at, String caller) { this.at = at; this.caller = caller; }
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            printerr("usage: CallSiteReport.java <out.json> <name> [<name> ...]");
            return;
        }
        FunctionManager fm = currentProgram.getFunctionManager();
        Map<String, List<Site>> report = new LinkedHashMap<>();
        for (int i = 1; i < args.length; i++) {
            String name = args[i];
            List<Function> targets = new ArrayList<>();
            addMatching(fm.getFunctions(true), name, targets);
            addMatching(fm.getExternalFunctions(), name, targets);
            List<Site> sites = new ArrayList<>();
            for (Function target : targets) {
                ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(target.getEntryPoint());
                while (refs.hasNext()) {
                    Reference ref = refs.next();
                    if (!ref.getReferenceType().isCall()) {
                        continue;
                    }
                    Function caller = fm.getFunctionContaining(ref.getFromAddress());
                    sites.add(new Site(ref.getFromAddress(), caller == null ? "" : caller.getName()));
                }
            }
            sites.sort(Comparator.comparing(s -> s.at));
            report.put(name, sites);
        }
        try (Writer w = new FileWriter(new File(args[0]))) {
            w.write(toJson(report));
        }
    }

    private static void addMatching(FunctionIterator it, String name, List<Function> out) {
        while (it.hasNext()) {
            Function f = it.next();
            if (f.getName().equals(name)) {
                out.add(f);
            }
        }
    }

    private static String toJson(Map<String, List<Site>> report) {
        StringBuilder sb = new StringBuilder("{");
        boolean firstKey = true;
        for (Map.Entry<String, List<Site>> e : report.entrySet()) {
            if (!firstKey) sb.append(", ");
            firstKey = false;
            sb.append(quote(e.getKey())).append(": [");
            boolean first = true;
            for (Site s : e.getValue()) {
                if (!first) sb.append(", ");
                first = false;
                sb.append("{\"caller\": ").append(quote(s.caller))
                  .append(", \"address\": ").append(quote(s.at.toString())).append("}");
            }
            sb.append("]");
        }
        return sb.append("}\n").toString();
    }

    private static String quote(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') sb.append('\\').append(c);
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        return sb.append('"').toString();
    }
}
