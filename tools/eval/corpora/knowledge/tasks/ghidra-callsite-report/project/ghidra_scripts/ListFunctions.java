// Prints every function in the current program with its entry point and size.
//@category Analysis
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class ListFunctions extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            println(f.getEntryPoint() + " " + f.getName() + " " + f.getBody().getNumAddresses());
        }
    }
}
