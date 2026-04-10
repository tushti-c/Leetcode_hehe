class Solution {
    public boolean isPalindrome(int x) {
        String string_x = String.valueOf(x);
        int len = string_x.length();
        for (int i = 0; i < Math.floorDiv(len,2); i++){
            if (string_x.charAt(i) != string_x.charAt(len - i-1)){
                return false;
            }
        }
        return true;
    }
}